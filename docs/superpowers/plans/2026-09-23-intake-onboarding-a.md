# One intake + onboarding foundations (Track I, part a) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every chat export the owner is about to request — a Claude zip, a ChatGPT folder with its
`user.json` and `chat.html` beside `conversations.json`, a Google Takeout zip holding Gemini's
`MyActivity.html` — imports through **one** pipeline that stamps the right origin, keeps each
message's time, reads every member it knows, names what it skipped, and never duplicates. Every way
a file reaches the app (a drop anywhere on the window, the Dock icon, File → Import… ⌘⇧I, the
menu-bar worm, an empty state, a `+` vendor tile) goes sniff → preview → import → a *what happens
next* card that never closes on its own; `UploadOverlay` and the Feed's Upload button retire. A
browser is read only after the person turned it on. And the pieces the one-screen Welcome (part b)
will stand on exist and are tested: the read-only agent-wiring probe, detection, the agent connect
that runs only after a click, and the honest pure functions (ruling 4 made visible).

**Architecture:** Backend first, app second, every decision a pure function with a table test.
The backend gains one router module (`api/routers/intake.py`: parse, plan, sniff, import) that the
two old import routes become shims over, a process-local job registry for large imports, a
read-only `GET /agents/wiring`, and one cicada-authored migration that stamps the origin the old
`+` path never wrote. The app gains one `@Observable` `IntakeRouter` (a request counter owns
`Store.intakeInFlight`, a generation token drops stale responses), one `IntakePanel` hosted by the
window overlay and by the `+` sheet, and the Meadow pieces the design names. **No new sync domain,
no ETag recipe changes** — the intake and wiring routes are request/response; `/sources/channels`
gains one row, not a field.

**Tech Stack:** Python 3.12 / FastAPI / Pydantic (`api/`), SwiftUI + XCTest (`app/CicadaApp`),
markdown + git bank.

**Binding sources.** Spec `docs/superpowers/specs/2026-09-23-round3-meadow-reach-provenance-design.md`
decisions 12–15. Design `docs/superpowers/specs/2026-09-23-round3-design-onboarding-intake-home.md`
§2 (F1–F13), §3, §4.3, §5, §7, §9, §10 and §12 **T1–T7** (this plan); T8–T12 are part b. Research
R7 §1–§2 lives in the session scratchpad and is **not committed** — every defect it names is
restated inline below with its own `file:line`. Backlog rows edited here: **G12, G20, G64, G87,
G117, G129**, plus one narrow note on **G125 R10**. G108 is ruled in part b. Standing rulings:
no prices or tokens in the app (2026-09-03), **ruling 4** (a scheduled cycle never spends plan
quota), ETag ship-together, the privacy rule, portability, G71 §4.3 (a preview stages nothing).

---

## What the code actually does today (verified against `feat/intake-onboarding` @ `c31fb00`)

App paths are relative to `app/CicadaApp/Sources/CicadaApp/`. Defect ids **D1–D14** are cited per
task.

**Consent (D1 = design F1).**
- `CicadaApp.swift:138-141` — `backend.start()` then `browserWatcher.start(store:)` on first
  `.onAppear`, before `store.bootstrap()` has resolved a bank.
- `Services/BrowserWatch.swift:207-214` — `start` arms every watch and runs `catchUp()`;
  `:225-232` — `catchUp` syncs any channel where `shouldSync(current:lastSynced:)` holds, and
  `:100-104` returns **true for `lastSynced == nil`**: a never-synced Chrome is imported at first
  launch with nobody asked. `:295-306` — the file-change path uses the same predicate. `:341-351` —
  the signature key is machine-global `cicada.browserWatch.<channel>`.
- `Support/FirstRunGate.swift` + `ContentView.swift:148-158` need `graphIsEmpty`; a bookmark
  import that lands first can keep the gate shut (F1b, inferred, not reproduced).
- Every user sync of a browser goes through `BrowserImportActions.syncChannel`
  (`Views/Capture/Sheets/BrowserImportPanels.swift:16-37`) from `ChannelActions.sync`
  (`Views/Sources/ChannelActions.swift:15-17`; callers `Views/Settings/IntegrationsView.swift:278,284`,
  `Views/Sources/ChannelSourceView.swift:77`, `Views/Sources/SourceCardGrid.swift:233`) and
  `Views/Feed/ConnectedChannelsStrip.swift:170-176`; the folder-scoped `+` import posts its own
  mutation at `BrowserImportPanels.swift:296-306`. None of them tells the watcher. The `Settings{}`
  scene (`CicadaApp.swift:229-236`) is **not** given the watcher in its environment.

**Two chat pipelines that disagree (D2 = F3, R7 §1.2 defects 1, 2, 6).**
- `api/routers/conversations.py:31-87` `POST /conversations/upload` — `.json`/`.html` only (no
  zip); **every** `.html` goes to `_parse_chatgpt_html` (a Gemini `MyActivity.html` included);
  parsers are called directly, so **no `origin`** is stamped (`_write_new_episode` writes `origin`
  only when the parser set it, `:908-912`); no date range. No backend test hits this route.
- `api/routers/banks.py:197-254` `POST /banks/{name}/import` → `parse_export_bytes`
  (`conversations.py:650-687`) which stamps origins and handles zips, returns `date_range`, and
  the G87 `active` flag.

**One zip member (D3).** `conversations.py:697-730` `_parse_zip` extracts the **first** match in
priority order: a Claude zip's `memories.json` and `projects.json` never import; any other
`MyActivity.html` (Search, YouTube) in a Takeout would be taken for Gemini.

**The "Unattributed" / "Claude Code" mis-credit (D4).** `source_overview.py:149-154` keys an
episode with no `origin` as `origin:unknown` ("Unattributed" on the Sources page).
`sleep_cycle.py:1371-1392` `_SOURCE_TO_ORIGIN` maps the importer's own `source: "claude"`,
`claude_memory`, `claude_project` to **`claude-code`**; it is read at `:1348`, `:1421` (claims'
`origin`) and `sleep_history.py:25-33`. Only the chat importer writes those `source` values
(`conversations.py:298, 336, 349, 403, 475, 508, 607`; `mcp/server.py:2059` writes `mcp`), so a
claude.ai export uploaded through `+` is credited to the Claude Code harness.

**The `+` flow (D5 = R7 defects 3–5).** `Views/Capture/Sheets/AddSourceSheet.swift:583-584` —
the one `chatExport` tile shows `WalkthroughPanel` and `pickChatExport` (`:782-792`: `.json/.html`,
no zip, no drop). `:881-907` `runImport` sums only created/skipped ("Imported N, skipped M" hides
G20's updated threads). `:909-927` `expandToFiles` walks folders without skipping `users.json`, so
every real export folder ends "(some files failed)". Nothing here sets `store.intakeInFlight`.

**The overlay (D6 = F4/F5).** `Views/Common/UploadOverlay.swift` — three modes (`:27-31`), its
own drop target (`:210-213`), auto-closes 1.5 s after success (`:441-447`), a literal
`Color.black.opacity(0.4)` scrim (`:64`), and is the only writer of the **Bool**
`Sync/Store.swift:90` `intakeInFlight`. `UploadHistoryStore` (`:619-656`) is written and **read
by nothing** (grep: no reader outside the file). `Views/Feed/FeedView.swift:55-86, 90-103` opts
back into `TopBarControls(showsUpload: true)` for exactly two reasons it states
(`Views/Common/TopBarControls.swift:28-37`); `Tests/CicadaAppTests/TopBarControlsTests.swift:52-66`
pins that opt-in. `Views/Sleep/SleepView.swift:277-283` passes `showsUpload: false` explicitly.

**HTML (D7).** `conversations.py:487-514` `_parse_chatgpt_html` falls back to `conversations =
[soup]` and turns every `div`/`p` longer than 10 characters into a role-`unknown` message dated
today — a bookmarks page or ChatGPT's JS `chat.html` viewer "imports" as garbage.

**Gemini (D8).** `conversations.py:568-615` — one episode per Takeout cell, **one `user` message
holding everything in the first content cell** (the prompt with its "Prompted" verb, and whatever
follows the timestamp line), titled `"Gemini activity"` every time, no `source_id` (content-hash
dedup). `api/tests/test_banks.py:388-420` pins format, count, dates and origin through the banks
route.

**Entry points (D9 = F10).** No `NSApplicationDelegateAdaptor`; `app/CicadaApp/bundle.sh:68-84`
writes an Info.plist with no `CFBundleDocumentTypes`; no File-menu import (`CicadaApp.swift:212-221`
holds only the View menu); `MenuBarManager.swift:190-236` has no import item.

**The graph eats drops (D10).** `Views/Graph/GraphView.swift:11-14` `ClickableWebView` is a
`WKWebView`, which registers for file drags itself: a file dropped on the Graph tab would be loaded
into the canvas, not reach a window-level `.onDrop`.

**Gemini has no channel (D11).** `source_overview.py:84-86` — `chat-export:gemini` has
`channel=None`; `channel_registry.py:36-45, 234-239` has no Gemini row;
`Models/IntegrationCategory.swift:41`, `Views/Capture/ChannelMarks.swift:19-23`,
`Views/Capture/ConnectedChannelRow.swift:211, 229, 249-262` and `AddSourceSheet.swift:125` know only
Claude and ChatGPT.

**Agent wiring (D12 = F8/F9).** `install.sh:55` `hook_command` is
`"<VENV_PY>" "<REPO>/api/hooks/capture.py" --harness <h>` with `VENV_PY=$API_DIR/.venv/bin/python`
(`:43-47`); `:277-321` registers the MCP server (`claude mcp add cicada -s user --env
CICADA_MEMORY_PATH=… -- <python> <server>`) and the Stop hook via `api/hooks/registry.py install`.
`api/hooks/registry.py:145-155` `status` returns `absent` for an unparseable file (so "off" and
"your file is broken" look the same); `load` raises `RegistryError` (`:44-53`); the CLI exits 3 on
it (`:186-188`). `Views/Connect/ConnectView.swift:46-138` `AgentSetupCatalog.all(home:memoryRoot:)`
builds the copy-paste commands as shell strings. `api/services/connections/base.py:52-74`
`resolve_binary`, `:112-140` `run_cli` (scrubbed env + `CICADA_CAPTURE=off`, rc 124 on timeout, 127
on a missing binary). **Measured on this machine, 2026-09-23** (claude 2.1.280, codex-cli 0.154.0,
outputs discarded): `claude mcp get <name>` exits **0** when registered (1.32 s, it health-checks
the server) and **1** when not (0.95 s); `codex mcp get <name> --json` exits **1** when not
registered (0.03–0.09 s); `codex mcp add <NAME> --env K=V -- <command…>` is the documented shape.

**The `turns` key and two sibling branches (D13).** On `dev`, `turns` exists only as an
**integer count** on Stop-hook episodes (`api/services/transcript_capture.py:261, 284`). Two
unmerged round-3 branches touch the importer's staging region (`conversations.py:743-943`):
`feat/provenance-viewer` `2a5ab0b` writes `turns: [{offset, ts, speaker}]` (helpers
`MAX_TURN_STAMPS`, `_message_line`, `_turn_stamps`); `feat/local-sources` `1010fef` moves staging
into a new `api/services/episode_staging.py` and writes a `turn_index` sidecar instead. Neither is
on `dev`.

**Also verified, not ours to fix (D14).** `_update_episode_in_place` (`conversations.py:924-943`)
re-queues without popping a stale `processed_by` (G114 R6); `feat/local-sources` `1010fef` already
fixes it in its stager.

**Meadow primitives on this base.** `Theme/CicadaMotion.swift:28-66` (the named durations, the
ambient drift constants `ambientMaxAmplitude` 8 / `ambientDefaultPeriod` 90), `:74-189`
`HoverLift`/`IconHover`/`hoverLift()`/`iconHover()`. `Theme/LiquidGlass.swift:123-137`
`PrimaryActionButton`, `:188-201` `primaryActionStyle()`. `Theme/CicadaTheme.swift:139, 148-157`
(`onAccent`, the nature tokens), `:315-324` `displayFont`/`quoteFont`. Lints that bind every new
file: `FontLiteralLintTests` (no `.system(size:)`), `MotionLiteralLintTests` (no `duration:` outside
`Theme/CicadaMotion.swift` and `Views/Sleep/SleepMotion.swift`), `LiquidGlassLintTests` (no
`.glassProminent`/`.glassEffect(` outside `Theme/LiquidGlass.swift`, and every `#available(macOS
26, *)` there paired with its own `#if canImport(SwiftUI, _version: 7.0)`), `ThemeTokenTests`
(no state hex outside the theme), `MeadowPlacementLintTests`, `CountLiteralLintTests`.

**Baselines on this base:** backend **2225 passed**, Swift **1012 executed, 0 failures**, graph
JS green (brief, 2026-09-06; re-measure before blaming a diff).

---

## Global Constraints

- Work ONLY in `<worktree>` = `<repo>/.worktrees/i` (branch
  `feat/intake-onboarding`, based on `dev` @ `c31fb00`). Every shell command is
  `cd <worktree> && <cmd>` with the ABSOLUTE path (zoxide hijacks a relative `cd`; ignore its
  stderr warning). Never an unquoted `--include=*.ext` (zsh globs it) — quote it or use `rg`.
- NEVER read `<repo>/memory` (any bank), `~/.cicada`, `~/Library/Safari` or `~/.claude/projects`.
  Fixtures are synthetic (`alpha-project`, `bob-example`, `example.com`) and come from
  `api/tests/_intake_fixtures.py` (Task 2).
- Python: `cd <worktree> && api/.venv/bin/python -m pytest <files> -q -p no:cacheprovider`; the full
  `api/tests` suite must report **0 failures**. If
  `test_agent_provenance.py::test_a_decay_only_change_lands_in_its_own_cicada_authored_commit` is the
  ONLY red, re-run it alone and report both results.
- Swift: `cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5` must succeed and
  `swift test 2>&1 | tail -20` must report **0 failures**. Graph JS:
  `cd <worktree> && node --test app/CicadaApp/Tests/graph/*.test.js`. SourceKit diagnostics naming
  OTHER worktrees are noise. NEVER run `make dev`, `make install-app`, `swift run`, or launch/kill
  the Cicada app or the launchd backend — the orchestrator installs and live-checks at the end.
- Never `git add -A`; stage named files only. Never commit `memory/`, `logs/`,
  `.claude/settings.json`, `api/.venv`, or `*-report.md`. No push, no new branches or worktrees, no
  subagents. Ignore Devin/PR comments.
- **Do not touch** `Views/Sleep/**` (Track Z owns it — `TopBarControls` keeps the parameters
  `SleepView.swift:277-283` passes), `Views/Capture/OriginIconography.swift`,
  `Views/Common/LogoImage.swift`, `Views/Common/OriginMark.swift` (Track L — consume only), and the
  staging functions `_stage_episodes` / `_write_new_episode` / `_update_episode_in_place` beyond the
  one byte-identical hunk R-IA6 names.
- **No LLM at capture.** Nothing in this plan calls an engine; the intake is file I/O and parsing.
- **Fonts** through `CicadaTheme.font(size:weight:design:)` or the named tokens; display serif only
  via `displayFont(size:)` at ≥ 22 pt. **Durations** only in `Theme/CicadaMotion.swift`. **Glass**
  only in `Theme/LiquidGlass.swift`. **Colours** only as theme tokens. **Counts** through
  `UsageFormat.count(_:locale:)`. **Marks** through `OriginIconography.logoName(for:)` →
  `LogoImage.platformTile`, never recoloured.
- **No prices, no token counts, no duration estimates** on any surface (2026-09-03, G107).
- **ETag ship-together:** no sync domain is added and no ETag recipe changes. `/sources/channels`
  gains one row (`chat-export:gemini`); its recipe and `VersionVector.swift` are untouched. If a task
  finds itself wanting a new domain, stop and say so.
- **Decode tolerance:** every new Swift wire type decodes a payload that omits any optional field.
- **Privacy (standing, 2026-09-02):** no owner name, no author-machine absolute path in shipped
  code, plans, commits or PR bodies; no bank contents in docs; placeholders only.
- Docstrings explain **why**, citing the G-row, the design fact (F1…), this plan's defect (D1…) or
  ruling (R-IA…) that motivated them. Match the density of the files touched.
- Line numbers are from `c31fb00` and drift as tasks land — read the cited code before editing.
- Every commit ends with the attribution line
  `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

---

## Rulings (binding)

The design's §10 rulings hold as written. Everything below is a choice the brief or design left
open, decided here with its reason so no task re-opens it.

- **R-IA1 — T6 lands before T5.** The brief lists T1…T7 "in dependency order", but T5's done card
  prints `ScheduleHonesty.afterImportLine` (A/B/C) and gates *Read now* on `EngineReadiness`. Built
  first, T5 would ship a hand-written "when will it be read" promise that T6 then replaces — the
  exact F7 defect (a nightly promise false under ruling 4). Task order: T1, T2, T2b, T3, T4, **T6,
  T5**, T7.
- **R-IA2 — consent is a flag beside the signature.** `cicada.browserWatch.enabled.<channel>`,
  machine-global like `cicada.browserWatch.<channel>` because the browser file is machine-global
  too. `isEnabled = flag ?? hasSignature`: a stored signature (an install that synced before this
  gate existed) counts as on, so nobody loses a watch; an explicit `false` outranks it (part b's
  "turn off"). Writers in part a: every user **Sync now** on a watched browser
  (`BrowserWatcher.syncNow`, which syncs through the watcher's own path so the signature is
  recorded once), and the `+` sheet's folder panel **only when every folder was imported** — a
  folder-scoped import stays one-shot, because the watch syncs the whole file and would widen the
  scope the person just narrowed (the G129 slice-2 folder-scope rail). The watch stays armed; only
  the sync is gated (design §4.3).
- **R-IA3 — a present, un-enabled browser reads "Off".** New `BrowserWatchState.off` (healthy,
  `textTertiary`, "Off" / "Cicada reads this browser only after you turn it on…"). `.stale` would
  say "Cicada hasn't caught up" about a browser nobody asked Cicada to read. On the Sources page it
  maps to the existing `.syncsOnDemand` verb, which is literally true, so `SourceLiveness` gains no
  state.
- **R-IA4 — F2 (a hand-off ends onboarding) ships with part b's T8, not here.** The defect lives
  entirely in `FirstRunSheet.swift:77` (`IntegrationsView(onHandOff: finish)`), which T8 deletes. A
  stopgap here either dismisses without marking — and `evaluateFirstRun` re-opens the sheet on the
  next graph snapshot, under the person's `+` sheet — or needs the Welcome's inline intake, which
  is T8. Spec decision 15's "ship first" is met by T8 landing it before any new onboarding UI.
- **R-IA5 — staging does not move here.** Design §9.1 item 1 moves `_stage_episodes` into
  `api/services/episode_staging.py`; `feat/local-sources` `1010fef` already does that move with a
  richer contract (drafts, scrub, rename-by-content). A second move here guarantees an add/add
  conflict on a 400-line file and a second stager API. The design's intent — a `plan()` that never
  writes and agrees with the stager — is met by `intake.plan()`, which mirrors `_stage_episodes`'
  decision rule clause for clause and is pinned to it by an agreement test over the same fixtures.
  When Local-sources lands, `plan()` becomes a call into its `scan`/`render` (a named follow-up,
  not a gap).
- **R-IA6 — `turns` exactly as the brief says, byte-identical to Provenance.** Task 2 adds
  `turns: [{offset, ts, speaker}]` by applying **the same hunk** `feat/provenance-viewer` `2a5ab0b`
  applies to `conversations.py` (`MAX_TURN_STAMPS = 500`, `_message_line`, `_turn_stamps`, the last
  frontmatter key, outside `content_hash`), so a three-way merge with that branch sees identical
  changes and resolves itself. Its test file is ours (`test_intake_turns.py`, never Provenance's
  `test_import_turn_stamps.py`, which needs `evidence.turn_starts` — not on `dev`). Known and
  disclosed: `turns` is an **int** on Stop-hook episodes, so any reader must check
  `isinstance(list)`; this plan adds no reader. Local-sources' `turn_index` naming disagrees — the
  orchestrator picks one before either merges (the plan's one open question).
- **R-IA7 — one parse entry, origin on every path.** `intake.parse_export(content, filename) ->
  ParsedExport` (episodes, wire `format`, vendor, origin, members, `ignored[]`, warnings, counts).
  `conversations.parse_export_bytes` stays as a 2-tuple wrapper over it for old callers. Every chat
  episode leaves with `claude-export`, `chatgpt-export` (the legacy HTML format included) or
  `gemini-export`.
- **R-IA8 — the zip reads every member it knows, and says what it didn't.** Named skips
  (`users.json`, `user.json`, `message_feedback.json`, `model_comparisons.json`,
  `shared_conversations.json`, `chat.html`) go to `ignored[{name, reason}]`; everything else that no
  parser recognises (images, attachments) is one counted warning, never a list of 300 file names.
  A `MyActivity.html` inside a zip is Gemini's only under a path naming Gemini (or Bard); other
  products' activity pages are ignored by name. Dropped alone: `chat.html` is **refused with the
  fix** ("…Drop conversations.json or the whole .zip."), a named skip is a **quiet skip**, and a
  `MyActivity.html` is Gemini's when its text names Gemini or Bard. A generic `.html` is ChatGPT's
  legacy export only if it has `div.conversation` blocks — the `[soup]` fallback (D7) goes, so a
  bookmarks page falls through to the saved-content path instead of importing as garbage.
- **R-IA9 — the Gemini parser splits prompt from reply, and re-imports never duplicate.** The cell
  text is split at its (last) timestamp line: before it is the prompt (its "Prompted"/"Asked"/"Said"
  verb stripped — the verb is Google's, not the person's words), after it the reply (`assistant`).
  Titles become the prompt's first line (≤ 60 chars). Because the body changes, each entry also
  carries `legacy_hash` — the hash the pre-T2 parser's body would have had — and `plan()` treats a
  legacy hash already in the bank as unchanged, so a Takeout re-imported into a bank that holds
  old-format Gemini episodes adds nothing. The pre-filter lives in the intake, so no staging code
  changes. The reply split is built against a synthetic fixture modelled on Takeout's documented
  cell shape; the owner's first real import is its live check (§ Verification 9).
- **R-IA10 — the shims.** `POST /conversations/upload` keeps its response model, runs
  `intake.import_bytes` synchronously (its callers expect counts), and sets `Deprecation: true`
  (the `nudges.py:16` pattern). `POST /banks/{name}/import` keeps its shape and gains optional
  `vendor`/`origin`. Only `POST /intake/import` backgrounds.
- **R-IA11 — the sniff contract.** Design §9.1 item 3's fields plus `platform` (for a saved-content
  sniff) and `titlesTruncated`. Kind resolution: chat parse first; on its refusal,
  `media_ingestor.preview_upload` (already staging-free); else `unknown` with the chat reason. A
  lone named skip answers `recognized: false`, `ignored: [it]`, `reason: null` — the app shows that
  as "Skipped", not as an error. `?bank=` computes the delta against that bank; the sniff never
  scaffolds a missing bank (it writes nothing).
- **R-IA12 — background staging.** Threshold: `plan()`'s `create + update > 10` (design §9.2).
  Staged in batches of 50 through the unchanged `_stage_episodes` (each batch re-scans, so ids and
  G20 identity stay exact across batches), progress `{staged, total}` never interpolated. One stage
  at a time per process (`intake_jobs.STAGING_LOCK`, taken by the sync path too): two overlapping
  stages into one bank would seed ids from the same max suffix and `markdown_parser.write`
  overwrites on collision (G114 R1). Jobs are process-local, kept one hour after they finish, 404
  when unknown.
- **R-IA13 — the origin repair is a migration, because it has to be.** A read-time fallback would
  need teaching separately to `source_overview`, `origin_stats`, `session_stats`, `sleep_history`
  and `sleep_cycle`; and `sleep_cycle` already writes the wrong harness into claims. Markdown is
  the source of truth (ruling 3): `export_origin_migration.backfill_export_origins` stamps `origin`
  once on every episode with **no `origin`, no `session_id`, and a `source` only the chat importer
  writes**, marker `.export_origins_v1`, committed over exactly the rewritten paths as
  `Cicada-Author: cicada`, trigger `maintenance/export_origin_backfill`, run from
  `bank_migrations`. It never touches `processed`, the body or `content_hash` — nothing re-queues,
  no evidence span moves. `_SOURCE_TO_ORIGIN` is corrected in the same commit for any bank not yet
  activated. Claims already consolidated keep their `claude-code` origin (claim origin carries no
  trust weight — `claim_pipeline.py:15-17`); rewriting claims is out of scope.
- **R-IA14 — the Gemini channel.** `chat-export:gemini`, label "Gemini chat export", noun
  **prompt** (one Takeout entry is one prompt and its reply, not a conversation). Until Task 7
  splits the tile, it maps to the existing `chatExport` tile (design §5.4).
- **R-IA15 — the wiring probe.** Harnesses: `claude-code` and `codex` (recall + auto-save +
  `connect`), `gemini-cli` read-only (recall from `~/.gemini/settings.json`, `connect: []` until its
  CLI is verified). The python in every command is **`<repo>/api/.venv/bin/python`** — install.sh's
  `VENV_PY`, spelled the same way — not `sys.executable`, because a differently spelled interpreter
  makes `registry.status` read every correct install as `stale`; `sys.executable` only when that
  path is missing. A `connect` step is offered only when needed: `mcp` iff recall is `off` (never
  on `unknown` — a registered server would make `mcp add` fail), `hook` iff auto-save is `off` or
  `stale`. `invalid` (a `RegistryError`) is its own state with a sentence, never `off`. Top-level
  `python`, `repo`, `memory` ride along so the app can pin its allowlist and build Cursor's deep link
  against the live memory root. `display == shlex.join(argv)`; `touches` are `~/`-relative.
- **R-IA16 — `MeadowPill`.** The owner's "muted green pill" (D-4, answered yes by default). Its style
  lives in `Theme/LiquidGlass.swift` (`meadowPillStyle()`), because the lint forbids
  `.glassProminent` anywhere else; the view is `Theme/MeadowPill.swift`. Part a uses it only for the
  intake panel's **Import** and the done card's **Read now**; everywhere else the primary stays
  `accent`.
- **R-IA17 — `MarkHover` lives in `Theme/CicadaMotion.swift`.** Its keyframes spell `duration:`,
  which `MotionLiteralLintTests` allows only there; it sits beside `IconHover`, as the design says.
- **R-IA18 — motion names.** New: `revealStagger` 0.04 s / `revealMaxRows` 8, `markNodDuration`
  0.32 s, `dropVeilDuration` 0.18 s, `successDuration` 0.4 s. The design's `cloudPeriod` /
  `cloudAmplitude` are **not** added: they are M1's `ambientDefaultPeriod` (90) and
  `ambientMaxAmplitude` (8), and two names for one value is the drift the vocabulary exists to stop.
- **R-IA19 — copy lives in `Theme/Copy+Intake.swift`** as `extension Copy`, so this track and the
  sibling tracks that append to `Copy.swift` never touch the same lines.
- **R-IA20 — the router's counter counts requests, not panels.** `Store.intakeInFlight` is true
  exactly while a sniff, an import or a job poll is in flight (design §5.1 "exactly while at least
  one runs"); a preview left open is not an intake landing. One intake at a time: a drop while an
  import runs is refused with a toast. `.feedPlus` renders in the `+` sheet; every other origin
  raises the window overlay. A job is polled to completion whether or not the panel is visible,
  because the flag and the post-import Store refresh both depend on knowing when it finished. There
  is no cancel once importing starts (nothing can be un-imported); closing only hides.
- **R-IA21 — three chat tiles.** `chatExport` becomes `claudeExport`, `chatgptExport`,
  `geminiExport`, each with its real mark (`OriginIconography.logoName(for: "<vendor>-export")`) and
  one channel; the family wears the three marks.
- **R-IA22 — `UploadOverlay` retires whole.** Its chat modes become the intake; its "Saved media"
  file mode becomes the intake's `kind: saved` path; its URL field is covered by the `+` sheet's
  *Paste a link* tile and the menu bar's *Save clipboard URL* (Home's paste box is part b).
  `UploadHistoryStore` goes with it (write-only, zero readers). `TopBarControls` keeps
  `showUploadOverlay`/`showsUpload` as **inert** parameters, because `Views/Sleep/SleepView.swift`
  passes them and Track Z owns that file; the Upload button's body is deleted and a lint pins that
  no call site passes `showsUpload: true`.
- **R-IA23 — until Track O's `EngineChooser`, "needs a choice" links to Settings.** When
  `EngineReadiness == .needsChoice`, the done card shows *Choose who reads first* as a
  `SettingsSectionLink(section: .sleep)` instead of *Read now*. *Read now* also hides when the
  import landed in a non-active bank: a read consolidates the active bank, not the one just filled.
- **R-IA24 — drops land in the router.** One window-level `.onDrop` in `ContentView`; the graph's
  `ClickableWebView` never registers dragged types (D10); the window is marked
  `.handlesExternalEvents(preferring: ["*"], allowing: ["*"])` so a Dock open reuses it instead of
  opening a second window.
- **R-IA25 — the Dock.** `@NSApplicationDelegateAdaptor(CicadaAppDelegate.self)` buffers URLs
  (`DockOpenQueue`) until the router attaches — a cold "Open With" delivers them before
  `.onAppear` runs. `CFBundleDocumentTypes`: role **Viewer**, `LSHandlerRank` **Alternate**, for
  `public.zip-archive`, `public.json`, `public.html`, `public.folder`, so Cicada is offered but never
  becomes the default opener.
- **R-IA26 — the menu bar gets the item only.** "Import a file…" between *Save clipboard URL* and
  *Open Cicada*. The status button as a drag destination is deferred (design §14 item 5 unverified
  on 14 and 26); the item is its keyboard twin.
- **R-IA27 — empty states that accept files.** Graph, Feed and Sources pass an `onDropFiles`
  closure with their own origin; Inbox passes none (nothing is imported there).
- **R-IA28 — `AgentConnect`'s allowlist is pinned to the app's own checkout.** Allowed: `<claude or
  codex binary the probe resolved> mcp add cicada [--scope user] --env CICADA_MEMORY_PATH=… --
  <installRoot>/api/.venv/bin/python <installRoot>/mcp/server.py`, and `<installRoot>/api/.venv/bin/python
  <installRoot>/api/hooks/registry.py install --settings <…/.claude/settings.json | …/.codex/hooks.json>
  --event Stop --command <…api/hooks/capture.py --harness …>`, where `installRoot` is
  `BackendProcess.installRoot()`. Anything else — including a backend running from a different
  checkout — is refused before anything runs, and the row falls back to *Copy commands* (D-1's
  fallback). Children run with `CICADA_CAPTURE=off`, the provider keys scrubbed, the binary's own
  directory first on `PATH`, 15 s per step; exit 3 is "not valid JSON, untouched".
- **R-IA29 — Claude Desktop is read, never written, in part a.** `LocalInventory` reads
  `~/Library/Application Support/Claude/claude_desktop_config.json` for `mcpServers.cicada` only
  when the app is installed (the app reads `~/Library`); its row's action is *Finish in Settings →
  Agents*. The JSON merge is optional T13. Whether macOS 26 shows an "App Data" prompt for that read
  is a live check (§ Verification 8).
- **R-IA30 — the `+` sheet root gains a drop zone (Task 7) and an "On this Mac" strip (Task 8).**
  The strip is `FoundRow`'s first host in part a: agents (Turn on → `AgentConnect`), Cursor (Turn on
  → its existing deep link), Claude Desktop (→ Settings), Chrome/Safari (Turn on →
  `BrowserWatcher.syncNow`; Safari blocked → *Allow…* opens Full Disk Access). No bookmark counts
  here (reading the file to count it on every sheet open is the Welcome's job, part b).
- **R-IA31 — Read now on the done card is G125 R10's first narrow amendment** (design §10): a user
  trigger, subtitled with `preview.manual`'s engine like Consolidate. Part b adds Getting started's.
  Recorded in the G125 row and CLAUDE.md.
- **R-IA32 — saved files commit through the path that previewed them.** A file the sniff calls
  `kind: saved` is imported with `POST /sources/upload` (the preview came from its staging-free
  twin); `POST /intake/import` is chat-only and answers 400 for anything else.
- **R-IA33 — the title filter is a local `localizedCaseInsensitiveContains`** until Track S's
  `QuickMatch` lands; the panel filters at most 5,000 titles and says so past the cap.

---

## File map

| File | Task | Responsibility |
|---|---|---|
| `app/…/Services/BrowserWatch.swift` | 1 | `.off` state; `enabledKey`, `isEnabled(flag:hasSignature:)`, `shouldSync(…enabled:)`; `BrowserWatcher.isEnabled/enable/syncNow`; `sync` returns its result |
| `app/…/Views/Sources/BrowserStatusLight.swift`, `SourceLiveness.swift`, `ChannelActions.swift` | 1 | `.off` copy; `.off → .syncsOnDemand`; `ChannelActions.sync(_:store:watcher:)` |
| `app/…/Views/Feed/ConnectedChannelsStrip.swift`, `Views/Settings/IntegrationsView.swift`, `Views/Sources/ChannelSourceView.swift`, `Views/Sources/SourceCardGrid.swift`, `Views/Capture/Sheets/BrowserImportPanels.swift`, `CicadaApp.swift` | 1 | pass the watcher; all-folders import enables; Settings scene gets the watcher |
| `api/routers/intake.py` (new) | 2, 3 | `ParsedExport`, `parse_export`, multi-member zip, `plan`, `import_bytes`, `sniff_bytes`; `POST /intake/sniff`, `POST /intake/import`, `GET /intake/jobs/{id}` |
| `api/routers/conversations.py` | 2 | the Provenance-identical `turns` hunk; Gemini parser; no `[soup]` fallback; `/conversations/upload` shim; `parse_export_bytes` wrapper; `_parse_zip` removed |
| `api/routers/banks.py` | 2 | `/banks/{name}/import` shim |
| `api/models/schemas.py` | 2, 3, 4 | `Intake*` models; `BankImportResponse.vendor/origin`; `IntakeJobStatus`; `AgentWiring*` |
| `api/main.py` | 2, 4 | mount `intake` and `agents` |
| `api/tests/_intake_fixtures.py` (new) | 2 | synthetic Claude/ChatGPT/Gemini exports; `python api/tests/_intake_fixtures.py <dir>` writes them |
| `api/services/intake_jobs.py` (new) | 3 | job registry, `STAGING_LOCK`, batched `run` |
| `api/services/channel_registry.py`, `api/services/source_overview.py` | 3 | `chat-export:gemini` |
| `api/services/sleep_cycle.py` | 3 | `_SOURCE_TO_ORIGIN` credits importer sources to their export |
| `api/services/export_origin_migration.py` (new), `api/services/bank_migrations.py` | 3 | the one-shot origin backfill |
| `app/…/Models/IntegrationCategory.swift`, `Views/Capture/ChannelMarks.swift`, `Views/Capture/ConnectedChannelRow.swift`, `Views/Capture/Sheets/AddSourceSheet.swift`, `Views/Sources/SourceBlurb.swift` | 3 | the Gemini channel in the app |
| `api/services/agent_wiring.py` (new), `api/routers/agents.py` (new), `api/tests/fixtures/agent_wiring_argv.json` (new) | 4 | `GET /agents/wiring`; the argv fixture both suites read |
| `app/…/Theme/CicadaTheme.swift`, `Theme/CicadaMotion.swift`, `Theme/LiquidGlass.swift`, `Theme/MeadowPill.swift` (new), `Theme/Copy+Intake.swift` (new), `Views/Common/FoundRow.swift` (new) | 5 | `onMeadow`, `scrim`; motion names + `MarkHover`; `meadowPillStyle()`; `MeadowPill`; strings; `FoundRow` |
| `app/…/Support/ScheduleHonesty.swift`, `EngineReadiness.swift`, `FoundPolicy.swift`, `OnboardingFlow.swift`, `HomeLayout.swift` (all new) | 6 | the pure logic |
| `app/…/Models/Intake.swift` (new) | 7 | wire models, `ChatVendor`, `IntakePreview`, `IntakeOutcome` |
| `app/…/Support/IntakeRouter.swift`, `IntakeSummary.swift`, `DockOpenQueue.swift` (all new) | 7 | the router, the sentences, the Dock buffer |
| `app/…/Views/Intake/IntakePanel.swift`, `IntakeDoneCard.swift`, `IntakeOverlay.swift` (all new) | 7 | the one panel, its done card, the overlay + drop veil |
| `app/…/Services/APIClient.swift`, `ContentView.swift`, `CicadaApp.swift`, `MenuBarManager.swift`, `Views/Graph/GraphView.swift`, `Views/Feed/FeedView.swift`, `Views/Common/TopBarControls.swift`, `Views/Common/EmptyStateView.swift`, `Views/Capture/Sheets/AddSourceSheet.swift`, `ImportFamilies.swift`, `WalkthroughPanel.swift`, `Theme/Copy.swift`, `Sync/Store.swift`, `app/CicadaApp/bundle.sh` | 7 | entry points; retire the overlay and Upload; three tiles; Gemini walkthrough |
| `app/…/Views/Common/UploadOverlay.swift` | 7 | **deleted** |
| `app/…/Models/AgentWiring.swift`, `Support/LocalInventory.swift`, `Support/AgentConnect.swift`, `Views/Intake/OnThisMacStrip.swift` (all new) | 8 | detection, connect, the `+` strip |
| Tests (Python) | 2–4 | `test_intake.py`, `test_intake_turns.py`, `test_intake_jobs.py`, `test_export_origin_migration.py`, `test_agent_wiring.py` (new); `test_source_channels.py` edited |
| Tests (Swift) | 1–8 | `BrowserWatchTests`, `SourcesV2Tests`, `ThemeTokenTests`, `CicadaMotionTests`, `CopyConstantsTests`, `TopBarControlsTests`, `ImportFamilyTests`, `AddSourceTileTests`, `ImportCatalogTests`, `WalkthroughTests`, `ChannelMarkTests`, `IntegrationsViewTests`, `FeedChannelStripTests`, `SourceChannelTests` edited; `MeadowPillTests`, `FoundRowTests`, `ScheduleHonestyTests`, `EngineReadinessTests`, `FoundPolicyTests`, `OnboardingFlowTests`, `HomeLayoutTests`, `IntakeRouterTests`, `IntakePreviewTests`, `IntakeSummaryTests`, `DockOpenQueueTests`, `BundleDocumentTypesTests`, `GraphDropTests`, `LocalInventoryTests`, `AgentConnectTests`, `AgentWiringCatalogTests` new |
| Docs | 1–8 | `CLAUDE.md`; `docs/goals/memory-evolution.md` rows G12, G20, G64, G87, G117, G125, G129; `docs/goals/TODO.md` |

---

### Task 1 (T1): Nothing is read before it is turned on

Spec decision 15's first defect (design §4.3, F1 = D1). Ships first, alone, because it is a
consent bug on the owner's own machine class: the first launch of a fresh install imports Chrome.

**Files:**
- Modify: `app/CicadaApp/Sources/CicadaApp/Services/BrowserWatch.swift` (`:59-78`, `:94-123`, `:207-232`, `:247-259`, `:295-330`)
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sources/BrowserStatusLight.swift:45-80`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sources/SourceLiveness.swift:70-76`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sources/ChannelActions.swift:15-17`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Feed/ConnectedChannelsStrip.swift:136, 170-176`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Settings/IntegrationsView.swift:278, 284` (+ the row's environment)
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sources/ChannelSourceView.swift:77`, `Views/Sources/SourceCardGrid.swift:233`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Capture/Sheets/BrowserImportPanels.swift:296-306`
- Modify: `app/CicadaApp/Sources/CicadaApp/CicadaApp.swift:229-236`
- Test: `app/CicadaApp/Tests/CicadaAppTests/BrowserWatchTests.swift`, `SourcesV2Tests.swift`
- Docs: `CLAUDE.md` (Awake rails), `docs/goals/memory-evolution.md` (G129)

**Interfaces:**
- Produces `BrowserWatchState.off`; `BrowserWatchPolicy.enabledKey(_:)`,
  `isEnabled(flag:hasSignature:)`, `shouldSync(current:lastSynced:enabled:)`,
  `state(fileExists:enabled:blocked:syncing:armed:upToDate:lastSyncFailed:)`;
  `BrowserWatcher.isEnabled(_:)`, `enable(_:)`, `syncNow(_:) async throws -> String`;
  `ChannelActions.sync(_:store:watcher:)`.
- Consumed by Task 8 (`OnThisMacStrip` calls `syncNow`; `LocalInventory` reads `isEnabled`) and
  part b's Welcome.

- [ ] **Step 1: Failing tests.** In `BrowserWatchTests.swift`, inside `BrowserWatchPolicyTests`,
  add:

```swift
    /// Track I T1 (design §4.3, F1) — first launch used to read Chrome before
    /// anyone was asked. A browser nobody turned on is never read, however old
    /// or new its file is.
    func testNothingSyncsBeforeTheChannelIsTurnedOn() {
        XCTAssertFalse(BrowserWatchPolicy.shouldSync(current: a, lastSynced: nil, enabled: false),
                       "F1: the never-synced case must not read without consent")
        XCTAssertTrue(BrowserWatchPolicy.shouldSync(current: a, lastSynced: nil, enabled: true))
        XCTAssertFalse(BrowserWatchPolicy.shouldSync(current: nil, lastSynced: nil, enabled: true),
                       "a missing file is still never a sync")
    }

    /// R-IA2 — an install that already synced a browser keeps it; an explicit
    /// off outranks that migration.
    func testAStoredSignatureCountsAsOnAndAnExplicitOffWins() {
        XCTAssertTrue(BrowserWatchPolicy.isEnabled(flag: nil, hasSignature: true))
        XCTAssertFalse(BrowserWatchPolicy.isEnabled(flag: nil, hasSignature: false))
        XCTAssertTrue(BrowserWatchPolicy.isEnabled(flag: true, hasSignature: false))
        XCTAssertFalse(BrowserWatchPolicy.isEnabled(flag: false, hasSignature: true))
        XCTAssertEqual(BrowserWatchPolicy.enabledKey("chrome-bookmarks"),
                       "cicada.browserWatch.enabled.chrome-bookmarks")
    }

    /// R-IA3 — present but not turned on reads Off, never Behind.
    func testAPresentBrowserNobodyTurnedOnReadsOff() {
        func state(exists: Bool = true, enabled: Bool, syncing: Bool = false) -> BrowserWatchState {
            BrowserWatchPolicy.state(fileExists: exists, enabled: enabled, blocked: false, syncing: syncing,
                                     armed: true, upToDate: false, lastSyncFailed: false)
        }
        XCTAssertEqual(state(enabled: false), .off)
        XCTAssertEqual(state(exists: false, enabled: false), .absent, "an absent browser is absent, on or off")
        XCTAssertEqual(state(enabled: false, syncing: true), .syncing, "what is happening now wins")
        XCTAssertEqual(state(enabled: true), .stale)
        XCTAssertTrue(BrowserWatchState.off.isHealthy, "not turned on is not a fault")
    }

    func testEveryLightStateHasItsOwnTitle() {
        let titles = BrowserWatchState.allCases.map(BrowserStatusLight.title(for:))
        XCTAssertEqual(Set(titles).count, titles.count)
    }
```

  In the same class's existing `testStatePrecedence`, the local helper gains `enabled: Bool = true`
  and passes it through (`BrowserWatchPolicy.state(fileExists: exists, enabled: enabled, blocked: …)`)
  — its assertions are unchanged. In `BrowserWatcherTests` add a helper and four tests, and call
  `turnOn()` as the first line of `testTheWatchSurvivesRepeatedAtomicReplaces` and
  `testASecondLaunchDoesNotResyncAnUnchangedFile`; rename
  `testCatchUpSyncsABrowserThatWasNeverSynced` to `testCatchUpSyncsATurnedOnBrowserThatWasNeverSynced`
  and call `turnOn()` first in it too:

```swift
    private func turnOn() { defaults.set(true, forKey: BrowserWatchPolicy.enabledKey("chrome-bookmarks")) }

    /// F1, end to end: the file exists, nobody turned the browser on, the app
    /// launches and the file changes — nothing is read, and the light says Off.
    func testFirstLaunchReadsNoBrowserBeforeConsent() async throws {
        try atomicallyReplace(with: "{}")
        var synced: [String] = []
        let watcher = makeWatcher { synced.append($0) }
        watcher.start(store: store)
        try await Task.sleep(for: .milliseconds(300))
        XCTAssertTrue(synced.isEmpty, "catch-up read a browser nobody turned on")
        XCTAssertEqual(watcher.state(for: "chrome-bookmarks"), .off)

        try atomicallyReplace(with: String(repeating: "x", count: 40))
        try await Task.sleep(for: .milliseconds(400))
        XCTAssertTrue(synced.isEmpty, "the file-change path is gated too")
        watcher.stop()
    }

    /// A Sync now is the consent: it turns the browser on, syncs ONCE through
    /// the watcher (so the signature is recorded), and the watch is live after.
    func testSyncNowTurnsTheBrowserOnSyncsOnceAndKeepsWatching() async throws {
        try atomicallyReplace(with: "{}")
        var synced: [String] = []
        let watcher = makeWatcher { synced.append($0) }
        watcher.start(store: store)
        let line = try await watcher.syncNow("chrome-bookmarks")
        XCTAssertEqual(line, "ok")
        XCTAssertEqual(synced, ["chrome-bookmarks"])
        XCTAssertEqual(defaults.object(forKey: BrowserWatchPolicy.enabledKey("chrome-bookmarks")) as? Bool, true)
        try await eventually("the light to settle") { watcher.state(for: "chrome-bookmarks") == .watching }

        try atomicallyReplace(with: String(repeating: "y", count: 50))
        try await eventually("the watch to pick up the next save") { synced.count == 2 }
        watcher.stop()
    }

    /// R-IA2's migration: an install that synced before the gate existed has a
    /// signature and no flag, and keeps syncing.
    func testAnInstallThatSyncedBeforeTheGateKeepsWatching() async throws {
        try atomicallyReplace(with: "{}")
        turnOn()
        var first: [String] = []
        let watcher = makeWatcher { first.append($0) }
        watcher.start(store: store)
        try await eventually("the first sync") { !first.isEmpty }
        watcher.stop()
        defaults.removeObject(forKey: BrowserWatchPolicy.enabledKey("chrome-bookmarks"))

        var second: [String] = []
        let relaunched = makeWatcher { second.append($0) }
        relaunched.start(store: store)
        try atomicallyReplace(with: String(repeating: "z", count: 60))
        try await eventually("a signature alone keeps the watch on") { !second.isEmpty }
        relaunched.stop()
    }

    /// The `+` panel's all-folders import calls `enable`, which catches up.
    func testEnableCatchesUp() async throws {
        try atomicallyReplace(with: "{}")
        var synced: [String] = []
        let watcher = makeWatcher { synced.append($0) }
        watcher.start(store: store)
        try await Task.sleep(for: .milliseconds(150))
        XCTAssertTrue(synced.isEmpty)
        watcher.enable("chrome-bookmarks")
        try await eventually("enable's catch-up") { synced == ["chrome-bookmarks"] }
        watcher.stop()
    }
```

  In `SourcesV2Tests.testLivenessNamesEveryStateTheCatalogCanProduce` add:

```swift
        // R-IA3 — a browser present but not turned on "syncs when you ask", which is exactly true.
        XCTAssertEqual(SourceLiveness.of(row: row("chrome-bookmarks", actions: ["sync"]),
                                         channel: nil, watch: .off).state, .syncsOnDemand)
```

  Run: `cd <worktree>/app/CicadaApp && swift test --filter "BrowserWatch|SourcesV2Tests" 2>&1 | tail -20`
  → compile failure (`enabled:` / `.off` / `syncNow` do not exist). That is the red.

- [ ] **Step 2: Implement `BrowserWatch.swift`.**
  - Add the case and fix `isHealthy` (`:59-78`):

```swift
    /// Present, but the person has not turned it on (Track I T1, design §4.3).
    /// Nothing is read until they do — that is the point, not a fault.
    case off
```
    and `var isHealthy: Bool { self == .watching || self == .syncing || self == .absent || self == .off }`.
  - Amend the doc comment on `shouldSync(current:lastSynced:)` (`:94-99`): "…that is the case that
    finally reads a browser the product has listed and never opened — **once the person turned it on**
    (Track I T1; `shouldSync(current:lastSynced:enabled:)` is what every caller uses)." Add below it:

```swift
    /// Track I T1 (design §4.3, F1): the per-channel consent flag. Machine-global,
    /// like the signature key beside it (`cicada.browserWatch.<channel>`), because
    /// the browser file it guards is machine-global too.
    static func enabledKey(_ channel: String) -> String { "cicada.browserWatch.enabled.\(channel)" }

    /// `flag` is what a person set; `nil` means nobody ever did. A stored
    /// signature means this install synced the browser before consent was a gate
    /// (G129 slice 1), so it counts as on — an existing user loses nothing. An
    /// explicit `false` outranks it (R-IA2).
    static func isEnabled(flag: Bool?, hasSignature: Bool) -> Bool { flag ?? hasSignature }

    /// F1: catch-up used to read any never-synced browser at first launch — before
    /// the first-run gate had decided anything, and able to make `graphIsEmpty`
    /// false under it (F1b). Consent comes first now; the signature rule is unchanged.
    static func shouldSync(current: BrowserFileSignature?, lastSynced: BrowserFileSignature?, enabled: Bool) -> Bool {
        enabled && shouldSync(current: current, lastSynced: lastSynced)
    }
```
  - `state(…)` gains `enabled: Bool` after `fileExists:` and returns `.off` after the absent check:

```swift
    static func state(
        fileExists: Bool,
        enabled: Bool,
        blocked: Bool,
        syncing: Bool,
        armed: Bool,
        upToDate: Bool,
        lastSyncFailed: Bool
    ) -> BrowserWatchState {
        if syncing { return .syncing }
        if blocked { return .blocked }
        if !fileExists { return .absent }
        if !enabled { return .off }
        if lastSyncFailed { return .failed }
        if armed && upToDate { return .watching }
        return .stale
    }
```
  - `catchUp()` (`:225-232`) and `syncIfChanged` (`:300-301`) call
    `BrowserWatchPolicy.shouldSync(current:lastSynced:enabled: isEnabled(channel))`.
    `refreshState` (`:247-259`) passes `enabled: isEnabled(channel)`; its `upToDate:` keeps the
    two-argument `shouldSync`.
  - Add to `BrowserWatcher`, after `func error(for:)`:

```swift
    func isEnabled(_ channel: String) -> Bool {
        BrowserWatchPolicy.isEnabled(
            flag: defaults.object(forKey: BrowserWatchPolicy.enabledKey(channel)) as? Bool,
            hasSignature: lastSynced(channel) != nil
        )
    }

    /// The person turned this browser on without a Sync now of their own (the
    /// `+` panel's all-folders import; part b's Welcome tick). Records consent and
    /// catches up through the watch's own path, so the signature is recorded and
    /// the light reads Watching.
    func enable(_ channel: String) {
        guard let file = channels.first(where: { $0.channel == channel })?.file else { return }
        defaults.set(true, forKey: BrowserWatchPolicy.enabledKey(channel))
        refreshState(channel: channel, file: file)
        Task { await syncIfChanged(channel: channel, file: file) }
    }

    /// A Sync now on a watched browser (R-IA2): turns it on, then syncs through the
    /// SAME path the watch uses — one sync, the signature recorded — and hands the
    /// one-line result back to the button that asked. Before this, a Sync now went
    /// around the watcher, so the watcher re-read the whole file on its next event.
    func syncNow(_ channel: String) async throws -> String {
        guard let file = channels.first(where: { $0.channel == channel })?.file else {
            throw BrowserImportActions.ImportActionError.failed("Unknown channel \(channel)")
        }
        defaults.set(true, forKey: BrowserWatchPolicy.enabledKey(channel))
        switch await sync(channel: channel, file: file) {
        case .success(let line)?: return line
        case .failure(let error)?: throw error
        case nil: return "Already syncing…"
        }
    }
```
  - `sync(channel:file:)` (`:308-330`) becomes `@discardableResult private func sync(channel:
    String, file: BrowserFile) async -> Result<String, Error>?` — `nil` for the existing early
    return; `.success(line)` where it now does `_ = try await performSync(...)`; `.failure(error)`
    in each catch (keeping both catches' bookkeeping exactly); the trailing `syncing.remove` /
    `refreshState` still run before `return result`.

- [ ] **Step 3: The light and the liveness verb.** `BrowserStatusLight.swift`: `color(for:)` →
  `case .off: CicadaTheme.textTertiary` (join it with `.absent`); `title(for:)` → `case .off:
  "Off"`; `explanation(for:)` → `case .off: "Cicada reads this browser only after you turn it on.
  Sync now brings its bookmarks in and keeps watching."`. `SourceLiveness.swift`, after the
  `watch == .watching` line: `if watch == .off { return .init(state: .syncsOnDemand, detail: nil) }`.

- [ ] **Step 4: Route every user sync through the watcher.**
  - `ChannelActions.swift`:

```swift
    /// Track I T1 (R-IA2): a Sync now on a watched browser IS the consent, so it
    /// goes through `BrowserWatcher.syncNow` — one sync, recorded, watch live.
    /// Unwatched channels (iCloud tabs, Notes' own route) are unchanged.
    static func sync(_ channelId: String, store: Store, watcher: BrowserWatcher?) async throws -> String {
        if let watcher, BrowserWatcher.isWatched(channelId) {
            return try await watcher.syncNow(channelId)
        }
        return try await BrowserImportActions.syncChannel(channelId, store: store)
    }
```
  - Callers pass the watcher they read from the environment: `ChannelSourceView.swift:77` and
    `SourceCardGrid.swift:233` already declare `@Environment(BrowserWatcher.self) private var watcher`
    in the same struct (`:15`, `:155`) → `ChannelActions.sync(channel.id, store: store, watcher:
    watcher)`. `IntegrationsView.swift`: the struct holding `trailingAction` (the row type around
    `:255-290`) gains `@Environment(BrowserWatcher.self) private var watcher`; both `:278` and `:284`
    pass it. `ConnectedChannelsStrip.swift`: the strip gains the same environment line; `:170` becomes
    `private static func sync(_ channel: SourceChannel, store: Store, watcher: BrowserWatcher)` and its
    last line `return try await ChannelActions.sync(channel.id, store: store, watcher: watcher)`; `:136`
    passes `watcher`.
  - `CicadaApp.swift:229-236` — the `Settings {}` scene gains `.environment(browserWatcher)` (after
    `.environment(store)`), because Integrations now reads it; without it that page traps.
  - `BrowserImportPanels.swift` `BookmarkFolderPanel`: add `@Environment(BrowserWatcher.self)
    private var watcher`; in `importSelected()` (`:296-306`), on success:

```swift
            if ok, let r = m.result {
                stage = .done(BrowserImportSummary.bookmarks(r))
                // R-IA2: importing EVERY folder is the same scope the watch syncs,
                // so it is consent to keep watching. A folder-scoped import stays
                // one-shot — the watch would widen what the person just narrowed.
                if folders == nil {
                    watcher.enable(browser == .chrome ? "chrome-bookmarks" : "safari-bookmarks")
                }
            }
```

- [ ] **Step 5: Green.** `cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5 && swift test 2>&1 | tail -20`
  → 0 failures.

- [ ] **Step 6: Docs.** `CLAUDE.md`, Awake rails, append to the first bullet ("The app reads
  `~/Library`, the backend parses bytes…"): " A browser is read only after the person turned it on
  — a Sync now, an all-folders import, or onboarding's tick — through
  `cicada.browserWatch.enabled.<channel>`; an install that synced before this gate keeps syncing
  (Track I T1)." `memory-evolution.md` G129 row, append to its status cell before the closing ` |`:

  > **Track I T1 amendment (2026-09-23, spec decision 15, design §4.3 F1):** catch-up no longer reads a browser nobody turned on — `BrowserWatchPolicy.shouldSync(current:lastSynced:enabled:)` gates both the launch catch-up and the file-change path on `cicada.browserWatch.enabled.<channel>` (machine-global, beside the signature key); a stored signature counts as on, so an install that already synced keeps syncing, and an explicit off outranks it. Writers: any Sync now on a watched browser (`BrowserWatcher.syncNow`, one sync through the watch's own path), an all-folders import from the `+` panel (a folder-scoped one stays one-shot — the watch would widen the scope the person narrowed), and part b's Welcome tick. A present-but-off browser reads **Off** (`BrowserWatchState.off`), never *Behind*. The watch stays armed; only the sync is gated.

- [ ] **Step 7: Commit.**

```bash
cd <worktree> && git add app/CicadaApp/Sources/CicadaApp/Services/BrowserWatch.swift \
  app/CicadaApp/Sources/CicadaApp/Views/Sources/BrowserStatusLight.swift \
  app/CicadaApp/Sources/CicadaApp/Views/Sources/SourceLiveness.swift \
  app/CicadaApp/Sources/CicadaApp/Views/Sources/ChannelActions.swift \
  app/CicadaApp/Sources/CicadaApp/Views/Sources/ChannelSourceView.swift \
  app/CicadaApp/Sources/CicadaApp/Views/Sources/SourceCardGrid.swift \
  app/CicadaApp/Sources/CicadaApp/Views/Feed/ConnectedChannelsStrip.swift \
  app/CicadaApp/Sources/CicadaApp/Views/Settings/IntegrationsView.swift \
  app/CicadaApp/Sources/CicadaApp/Views/Capture/Sheets/BrowserImportPanels.swift \
  app/CicadaApp/Sources/CicadaApp/CicadaApp.swift \
  app/CicadaApp/Tests/CicadaAppTests/BrowserWatchTests.swift \
  app/CicadaApp/Tests/CicadaAppTests/SourcesV2Tests.swift CLAUDE.md docs/goals/memory-evolution.md
git commit -m "fix(browsers): nothing is read before it is turned on (Track I T1, G129 amendment)" \
  -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2 (T2): One pipeline for every chat export

Design §9.1 items 1–6 (D2, D3, D7, D8), the `turns` sidecar (R-IA6), and the two old routes as
shims (R-IA10). Backend only; the app keeps calling the old routes until Task 7, so the branch stays
shippable.

**Files:**
- Create: `api/routers/intake.py`
- Create: `api/tests/_intake_fixtures.py`
- Modify: `api/routers/conversations.py` (`:31-87` shim, `:487-514` HTML, `:568-615` Gemini, `:650-731` wrapper + `_parse_zip` removed, `:743-943` the R-IA6 hunk)
- Modify: `api/routers/banks.py:28, 197-254`
- Modify: `api/models/schemas.py` (after `BankImportResponse`, `:1459-1471`)
- Modify: `api/main.py:13-39, 169`
- Test: `api/tests/test_intake.py` (new), `api/tests/test_intake_turns.py` (new)
- Docs: `CLAUDE.md` (Features §5, endpoint traps), `docs/goals/memory-evolution.md` (G12, G20)

**Interfaces:**
- Produces `intake.parse_export(content, filename) -> ParsedExport`, `intake.plan(episodes,
  memory_path) -> StagePlan`, `intake.import_bytes(content, filename, settings, *, bank=None) ->
  ImportResult`, `intake.sniff_bytes(content, filename, settings, bank) -> IntakeSniffResponse`,
  `intake.source_label(parsed)`; routes `POST /intake/sniff?bank=`, `POST /intake/import?bank=`.
- Wire (camelCase): `IntakeSniffResponse {recognized, kind, vendor, origin, platform, members,
  ignored[{name, reason}], counts{conversations, memories, projects, prompts, items},
  dateRange{from,to}, delta{new, grown, unchanged}, titles[{title, date}], titlesTruncated, reason,
  warnings}`; `IntakeImportResponse {episodesStaged, episodesUpdated, duplicatesSkipped, dateRange,
  format, active, bank, vendor, origin, members, ignored, job}` (`job` stays `null` until Task 3).
- Consumed by Task 3 (jobs), Task 7 (`APIClient.sniffIntake` / `importIntake`).

- [ ] **Step 1: The fixtures module** — `api/tests/_intake_fixtures.py`, stdlib only:

```python
"""Synthetic chat exports for the one-intake tests (Track I T2) and the live pass.

Stdlib only, so the orchestrator can write them anywhere without the API
installed:

    api/.venv/bin/python api/tests/_intake_fixtures.py <dir>

Every value is a placeholder (alpha-project, bob-example, example.com); the
shapes are the ones the parsers in ``api/routers/conversations.py`` document,
never copied from a real export. Underscore prefix: pytest never collects it;
sibling tests import it as ``from _intake_fixtures import …`` (the
``_synthetic_bank`` pattern — ``api/tests`` has no ``__init__.py``).
"""
from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path


def claude_conversations(n: int = 2, *, grown: bool = False) -> list[dict]:
    out = []
    for i in range(n):
        day = 1 + (i % 27)
        stamp = f"2026-02-{day:02d}T12:00"
        msgs = [
            {"uuid": f"c{i}-m0", "sender": "human", "text": f"How is alpha-project going? ({i})",
             "content": [], "created_at": f"{stamp}:00.000000Z"},
            {"uuid": f"c{i}-m1", "sender": "assistant", "text": "It ships on Friday.",
             "content": [], "created_at": f"{stamp}:05.000000Z"},
        ]
        if grown and i == 0:
            msgs.append({"uuid": "c0-m2", "sender": "human", "text": "Ask bob-example to review it.",
                         "content": [], "created_at": f"{stamp}:40.000000Z"})
        out.append({"uuid": f"conv-{i}", "name": f"alpha-project check-in {i}",
                    "created_at": f"{stamp}:00.000000Z", "updated_at": f"{stamp}:{50 if grown and i == 0 else 30}.000000Z",
                    "chat_messages": msgs})
    return out


def claude_memories() -> list[dict]:
    return [{"conversations_memory": "Works on alpha-project with bob-example.",
             "project_memories": {"p-0123456789": "alpha-project stores vectors in sqlite-vec."},
             "updated_at": "2026-03-01T09:00:00Z"}]


def claude_projects() -> list[dict]:
    return [{"name": "alpha-project", "description": "A synthetic project.", "prompt_template": "",
             "created_at": "2026-01-10T08:00:00Z"},
            {"name": "How to use Claude", "description": "default", "prompt_template": "",
             "created_at": "2026-01-01T00:00:00Z"}]


def chatgpt_conversations(n: int = 2) -> list[dict]:
    out = []
    for i in range(n):
        t0 = 1_700_000_000 + i * 86_400
        out.append({"conversation_id": f"gpt-{i}", "title": f"bob-example notes {i}",
                    "create_time": t0, "update_time": t0 + 60, "mapping": {
                        "a": {"message": {"author": {"role": "user"},
                                          "content": {"parts": [f"Draft a note for bob-example ({i})"]},
                                          "create_time": t0}},
                        "b": {"message": {"author": {"role": "assistant"},
                                          "content": {"parts": ["Here is a short note."]},
                                          "create_time": t0 + 30}}}})
    return out


CHAT_HTML = "<html><body><div id=\"root\"></div><script>var jsonData = [];</script></body></html>"

GEMINI_ENTRIES = (
    ("Summarize my alpha-project notes", "Here is a summary of alpha-project.", "Feb 24, 2026, 12:39:02 PM PST"),
    ("Plan a visit to example.com", None, "Nov 3, 2025, 8:00:00 AM PST"),
)


def gemini_activity_html(entries=GEMINI_ENTRIES, *, product: str = "Gemini Apps", verb: str = "Prompted") -> str:
    """Takeout's documented cell: a header cell naming the product, then a
    content cell holding ``<verb>&nbsp;<prompt><br><date>`` and, for Gemini,
    the reply after the date."""
    cells = []
    for prompt, reply, when in entries:
        tail = f"<br><p>{reply}</p>" if reply else ""
        cells.append(
            '<div class="outer-cell mdl-cell mdl-cell--12-col"><div class="mdl-grid">'
            f'<div class="header-cell mdl-cell mdl-cell--12-col"><p class="mdl-typography--title">{product}<br></p></div>'
            f'<div class="content-cell mdl-cell mdl-cell--6-col mdl-typography--body-1">{verb} {prompt}<br>{when}{tail}</div>'
            '</div></div>')
    return "<!DOCTYPE html><html><body>" + "".join(cells) + "</body></html>"


BOOKMARKS_HTML = """<!DOCTYPE NETSCAPE-Bookmark-file-1>
<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">
<TITLE>Bookmarks</TITLE><H1>Bookmarks</H1>
<DL><p><DT><H3>alpha-project</H3><DL><p>
<DT><A HREF="https://example.com/one" ADD_DATE="1700000000">One</A>
<DT><A HREF="https://example.com/two" ADD_DATE="1700000100">Two</A>
</DL><p></DL><p>
"""


def _zip(files: dict[str, bytes | str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data if isinstance(data, bytes) else data.encode())
    return buf.getvalue()


def claude_zip(n: int = 2) -> bytes:
    return _zip({"conversations.json": json.dumps(claude_conversations(n)),
                 "memories.json": json.dumps(claude_memories()),
                 "projects.json": json.dumps(claude_projects()),
                 "users.json": json.dumps([{"uuid": "u-1", "full_name": "bob-example",
                                            "email_address": "bob@example.com"}])})


def chatgpt_loose_files(n: int = 2) -> dict[str, bytes | str]:
    return {"conversations.json": json.dumps(chatgpt_conversations(n)),
            "chat.html": CHAT_HTML,
            "user.json": json.dumps({"id": "user-1", "email": "bob@example.com"}),
            "message_feedback.json": "[]",
            "model_comparisons.json": "[]",
            "shared_conversations.json": json.dumps([{"id": "s-1", "conversation_id": "gpt-0", "title": "x"}]),
            "file-0001.png": b"\x89PNG\r\n"}


def chatgpt_zip(n: int = 2) -> bytes:
    return _zip(chatgpt_loose_files(n))


def gemini_takeout_zip() -> bytes:
    return _zip({"Takeout/My Activity/Gemini Apps/MyActivity.html": gemini_activity_html(),
                 "Takeout/My Activity/Gemini Apps/image-1.png": b"\x89PNG\r\n",
                 "Takeout/My Activity/Search/MyActivity.html":
                     gemini_activity_html((("example.com opening hours", None, "Jan 5, 2026, 9:00:00 AM PST"),),
                                          product="Search", verb="Searched for"),
                 "Takeout/archive_browser.html": "<html><body>index</body></html>"})


def write_all(directory: Path) -> list[Path]:
    """The live pass's inputs (§ Verification): three zips, a loose ChatGPT
    folder, a 50-conversation Claude file (the background job), a bookmarks page."""
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for name, data in {"claude-export.zip": claude_zip(),
                       "chatgpt-export.zip": chatgpt_zip(),
                       "gemini-takeout.zip": gemini_takeout_zip(),
                       "claude-50.json": json.dumps(claude_conversations(50)).encode(),
                       "bookmarks.html": BOOKMARKS_HTML.encode()}.items():
        (directory / name).write_bytes(data)
        written.append(directory / name)
    folder = directory / "chatgpt-export"
    folder.mkdir(exist_ok=True)
    for name, data in chatgpt_loose_files().items():
        (folder / name).write_bytes(data if isinstance(data, bytes) else data.encode())
    written.append(folder)
    return written


if __name__ == "__main__":
    for path in write_all(Path(sys.argv[1])):
        print(path)
```

- [ ] **Step 2: Failing tests** — `api/tests/test_intake.py`:

```python
"""Track I T2 — one pipeline for every chat export (design §9.1, spec decision 13).

Synthetic exports only (``_intake_fixtures``); no network, no real bank.
"""
from __future__ import annotations

import hashlib
import json

import pytest
from fastapi import HTTPException

from _intake_fixtures import (BOOKMARKS_HTML, CHAT_HTML, chatgpt_zip, claude_conversations,
                              claude_zip, gemini_activity_html, gemini_takeout_zip)
from api import config
from api.routers import conversations as conv
from api.routers import intake
from api.services import bank_registry, markdown_parser


def _client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from api import main
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path))
    config.get_settings.cache_clear()
    bank_registry.scaffold_bank(tmp_path, git_init=False)
    return TestClient(main.app)


def _post(client, route, name, data, **params):
    body = data if isinstance(data, bytes) else data.encode()
    return client.post(route, params=params, files={"file": (name, body, "application/octet-stream")})


def _episodes(tmp_path):
    return {p.stem: markdown_parser.parse(p) for p in (tmp_path / "episodes").glob("*.md")}


def _tree(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


# --- parse_export: zips, skips, refusals (R-IA7, R-IA8) ---------------------


def test_a_claude_zip_parses_every_member_and_names_the_account_file():
    parsed = intake.parse_export(claude_zip(), "data-2026.zip")
    assert sorted(parsed.members) == ["conversations.json", "memories.json", "projects.json"]
    assert parsed.ignored == [{"name": "users.json", "reason": intake.SKIPPED_MEMBERS["users.json"]}]
    assert parsed.counts == {"conversations": 2, "memories": 2, "projects": 1}
    assert parsed.vendor == "claude" and parsed.format == "claude"
    assert {e["origin"] for e in parsed.episodes} == {"claude-export"}, "D2: every path stamps"


def test_a_chatgpt_zip_skips_its_known_extras_by_name_and_counts_the_rest():
    parsed = intake.parse_export(chatgpt_zip(), "export.zip")
    assert parsed.members == ["conversations.json"]
    assert sorted(i["name"] for i in parsed.ignored) == [
        "chat.html", "message_feedback.json", "model_comparisons.json",
        "shared_conversations.json", "user.json"]
    assert parsed.warnings == ["1 other file in the zip isn't a conversation (images, attachments, settings)."]
    assert {e["origin"] for e in parsed.episodes} == {"chatgpt-export"}


def test_a_gemini_takeout_zip_reads_only_gemini_activity():
    parsed = intake.parse_export(gemini_takeout_zip(), "takeout-2026.zip")
    assert parsed.vendor == "gemini" and parsed.counts == {"prompts": 2}
    assert {"name": "Search/MyActivity.html", "reason": intake.OTHER_ACTIVITY} in parsed.ignored
    assert {e["origin"] for e in parsed.episodes} == {"gemini-export"}


def test_chat_html_alone_is_refused_with_the_fix():
    with pytest.raises(HTTPException) as exc:
        intake.parse_export(CHAT_HTML.encode(), "chat.html")
    assert exc.value.status_code == 400 and exc.value.detail == intake.CHAT_HTML_REASON


def test_activity_for_another_product_alone_is_refused():
    page = gemini_activity_html((("example.com hours", None, "Jan 5, 2026, 9:00:00 AM PST"),),
                                product="Search", verb="Searched for")
    with pytest.raises(HTTPException) as exc:
        intake.parse_export(page.encode(), "MyActivity.html")
    assert exc.value.detail == intake.NOT_GEMINI_REASON


def test_a_bookmarks_page_is_not_a_chat_export():
    """D7: the `[soup]` fallback imported any page as role-less chat."""
    with pytest.raises(HTTPException) as exc:
        intake.parse_export(BOOKMARKS_HTML.encode(), "bookmarks.html")
    assert exc.value.detail == intake.NOT_A_CHAT_PAGE


def test_a_lone_account_file_is_a_quiet_skip():
    parsed = intake.parse_export(b'{"id": "user-1"}', "user.json")
    assert parsed.episodes == [] and parsed.ignored[0]["name"] == "user.json"


# --- Gemini (R-IA9) ----------------------------------------------------------


def test_the_gemini_parser_splits_prompt_from_reply_and_titles_by_the_prompt():
    [first, second] = sorted(conv.parse_gemini_myactivity(gemini_activity_html()),
                             key=lambda e: e["timestamp"], reverse=True)
    assert [(m["role"], m["text"]) for m in first["messages"]] == [
        ("user", "Summarize my alpha-project notes"), ("assistant", "Here is a summary of alpha-project.")]
    assert first["title"] == "Summarize my alpha-project notes"
    assert first["timestamp"] == "2026-02-24T12:39:02+00:00"
    assert [m["role"] for m in second["messages"]] == ["user"], "no reply, no assistant line"
    assert all(e["origin"] == "gemini-export" and e["legacy_hash"] for e in (first, second))


def test_a_takeout_reimported_after_the_parser_change_duplicates_nothing(tmp_path, monkeypatch):
    """R-IA9: stage the body the pre-T2 parser wrote, then import the same Takeout."""
    ep_dir = tmp_path / "episodes"
    ep_dir.mkdir(parents=True)
    for i, ep in enumerate(conv.parse_gemini_myactivity(gemini_activity_html())):
        text = "Prompted " + ep["messages"][0]["text"]
        if len(ep["messages"]) > 1:
            text += "\n\n" + ep["messages"][1]["text"]
        body = f"user: {text}"
        assert hashlib.sha256(body.encode()).hexdigest()[:12] == ep["legacy_hash"]
        markdown_parser.write(ep_dir / f"ep_2026-01-01_00{i + 1}.md",
                              {"id": f"ep_2026-01-01_00{i + 1}", "origin": "gemini-export", "source": "gemini_export",
                               "processed": True, "content_hash": ep["legacy_hash"]}, body)
    client = _client(tmp_path, monkeypatch)
    r = _post(client, "/intake/import", "MyActivity.html", gemini_activity_html())
    assert r.status_code == 200, r.text
    assert (r.json()["episodesStaged"], r.json()["duplicatesSkipped"]) == (0, 2)
    assert len(list(ep_dir.glob("*.md"))) == 2
    config.get_settings.cache_clear()


# --- plan() agrees with the stager (R-IA5) -----------------------------------


def test_plan_agrees_with_stage_for_new_grown_and_unchanged(tmp_path):
    ep_dir = tmp_path / "episodes"
    conv._stage_episodes(conv.parse_anthropic_conversations(claude_conversations(3)), ep_dir)
    second = conv.parse_anthropic_conversations(claude_conversations(4, grown=True))
    predicted = intake.plan(second, tmp_path)
    assert (len(predicted.create), len(predicted.update), len(predicted.skip)) == (1, 1, 2)
    assert conv._stage_episodes(second, ep_dir) == (1, 1, 2), "plan and stage must never disagree"
    again = intake.plan(conv.parse_anthropic_conversations(claude_conversations(4, grown=True)), tmp_path)
    assert (len(again.create), len(again.update), len(again.skip)) == (0, 0, 4)


# --- the sniff stages nothing (G71 §4.3, R-IA11) ------------------------------


def test_the_sniff_writes_nothing_and_says_what_is_inside(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    before = _tree(tmp_path)
    r = _post(client, "/intake/sniff", "export.zip", claude_zip())
    assert r.status_code == 200, r.text
    assert _tree(tmp_path) == before, "a sniff must not write a byte"
    body = r.json()
    assert body["recognized"] and body["kind"] == "chat" and body["vendor"] == "claude"
    assert body["origin"] == "claude-export"
    assert body["counts"]["conversations"] == 2 and body["counts"]["memories"] == 2
    assert body["dateRange"] == {"from": "2026-01-10", "to": "2026-03-01"}
    assert body["delta"] == {"new": 5, "grown": 0, "unchanged": 0}
    assert body["ignored"][0]["name"] == "users.json"
    assert body["titles"][0]["date"] >= body["titles"][-1]["date"], "newest first"
    config.get_settings.cache_clear()


def test_the_sniff_caps_titles(tmp_path, monkeypatch):
    monkeypatch.setattr(intake, "MAX_SNIFF_TITLES", 1)
    client = _client(tmp_path, monkeypatch)
    body = _post(client, "/intake/sniff", "conversations.json", json.dumps(claude_conversations(3))).json()
    assert len(body["titles"]) == 1 and body["titlesTruncated"] is True
    config.get_settings.cache_clear()


def test_a_bookmarks_page_sniffs_as_saved_content(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    body = _post(client, "/intake/sniff", "bookmarks.html", BOOKMARKS_HTML).json()
    assert body["recognized"] and body["kind"] == "saved" and body["counts"]["items"] == 2
    config.get_settings.cache_clear()


def test_a_lone_account_file_sniffs_as_a_quiet_skip(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    body = _post(client, "/intake/sniff", "user.json", '{"id": "user-1"}').json()
    assert body["recognized"] is False and body["reason"] is None
    assert body["ignored"] == [{"name": "user.json", "reason": intake.SKIPPED_MEMBERS["user.json"]}]
    config.get_settings.cache_clear()


def test_an_unreadable_file_sniffs_with_its_reason(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    body = _post(client, "/intake/sniff", "chat.html", CHAT_HTML).json()
    assert body["recognized"] is False and body["reason"] == intake.CHAT_HTML_REASON
    config.get_settings.cache_clear()


# --- import: origin, dates, no duplicates (G12, G20) --------------------------


def test_import_stamps_origin_keeps_dates_and_a_reimport_duplicates_nothing(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    first = _post(client, "/intake/import", "export.zip", claude_zip()).json()
    assert (first["episodesStaged"], first["episodesUpdated"], first["duplicatesSkipped"]) == (5, 0, 0)
    assert first["vendor"] == "claude" and first["origin"] == "claude-export" and first["active"] is True
    eps = _episodes(tmp_path)
    assert {p.frontmatter["origin"] for p in eps.values()} == {"claude-export"}
    assert "ep_2026-02-01_001" in eps, "backdated to the conversation's own date"
    again = _post(client, "/intake/import", "export.zip", claude_zip()).json()
    assert (again["episodesStaged"], again["duplicatesSkipped"]) == (0, 5)
    assert len(_episodes(tmp_path)) == 5
    config.get_settings.cache_clear()


def test_a_grown_thread_is_updated_in_place(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _post(client, "/intake/import", "conversations.json", json.dumps(claude_conversations(2)))
    r = _post(client, "/intake/import", "conversations.json", json.dumps(claude_conversations(2, grown=True))).json()
    assert (r["episodesStaged"], r["episodesUpdated"], r["duplicatesSkipped"]) == (0, 1, 1)
    config.get_settings.cache_clear()


def test_import_into_an_unknown_bank_is_404(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    assert _post(client, "/intake/import", "export.zip", claude_zip(), bank="nope").status_code == 404
    config.get_settings.cache_clear()


# --- the shims (R-IA10) ------------------------------------------------------


def test_the_conversations_upload_shim_now_stamps_origin_and_is_deprecated(tmp_path, monkeypatch):
    """R7 §1.2 defect 1: a Claude export through `+` read "Unattributed"."""
    client = _client(tmp_path, monkeypatch)
    r = _post(client, "/conversations/upload", "conversations.json", json.dumps(claude_conversations(2)))
    assert r.status_code == 200 and r.headers["Deprecation"] == "true"
    assert r.json()["episodesCreated"] == 2 and r.json()["source"] == "Claude — Conversations"
    assert {p.frontmatter["origin"] for p in _episodes(tmp_path).values()} == {"claude-export"}
    zipped = _post(client, "/conversations/upload", "export.zip", chatgpt_zip())
    assert zipped.status_code == 200 and zipped.json()["episodesCreated"] == 2, "defect 3: zips accepted"
    gem = _post(client, "/conversations/upload", "MyActivity.html", gemini_activity_html())
    assert gem.json()["source"] == "Gemini — Activity", "defect 2: the Gemini parser, not ChatGPT's scraper"
    config.get_settings.cache_clear()


def test_the_banks_import_shim_keeps_its_shape_and_adds_vendor_and_origin(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    client.post("/banks", json={"name": "Imports"})
    body = _post(client, "/banks/imports/import", "export.zip", claude_zip()).json()
    assert body["format"] == "claude" and body["episodesStaged"] == 5 and body["active"] is False
    assert body["vendor"] == "claude" and body["origin"] == "claude-export"
    config.get_settings.cache_clear()
```

  And `api/tests/test_intake_turns.py` (R-IA6 — our own file; Provenance's is
  `test_import_turn_stamps.py`):

```python
"""Track I T2 (R-IA6) — each message's time rides beside the body as
``turns: [{offset, ts, speaker}]``, outside ``content_hash`` (the brief's shape,
byte-identical to feat/provenance-viewer 2a5ab0b)."""
from __future__ import annotations

import hashlib

from _intake_fixtures import claude_conversations
from api.routers import conversations as conv
from api.services import markdown_parser


def _only(ep_dir):
    [path] = list(ep_dir.glob("*.md"))
    return markdown_parser.parse(path)


def test_an_import_keeps_each_message_time_as_the_last_key(tmp_path):
    conv._stage_episodes(conv.parse_anthropic_conversations(claude_conversations(1)), tmp_path / "episodes")
    parsed = _only(tmp_path / "episodes")
    turns = parsed.frontmatter["turns"]
    first = "user: How is alpha-project going? (0)"
    assert turns == [
        {"offset": 0, "ts": "2026-02-01T12:00:00+00:00", "speaker": "user"},
        {"offset": len(first) + 1, "ts": "2026-02-01T12:00:05+00:00", "speaker": "assistant"},
    ]
    assert list(parsed.frontmatter)[-1] == "turns"
    for t in turns:
        assert parsed.body[t["offset"]:].startswith(f"{t['speaker']}:")


def test_the_sidecar_never_enters_the_content_hash(tmp_path):
    conv._stage_episodes(conv.parse_anthropic_conversations(claude_conversations(1)), tmp_path / "episodes")
    parsed = _only(tmp_path / "episodes")
    assert parsed.frontmatter["content_hash"] == hashlib.sha256(parsed.body.encode()).hexdigest()[:12]


def test_an_unchanged_reimport_is_a_byte_identical_skip(tmp_path):
    ep_dir = tmp_path / "episodes"
    conv._stage_episodes(conv.parse_anthropic_conversations(claude_conversations(1)), ep_dir)
    [path] = list(ep_dir.glob("*.md"))
    before = path.read_bytes()
    assert conv._stage_episodes(conv.parse_anthropic_conversations(claude_conversations(1)), ep_dir) == (0, 0, 1)
    assert path.read_bytes() == before


def test_a_grown_reimport_rewrites_the_sidecar(tmp_path):
    ep_dir = tmp_path / "episodes"
    conv._stage_episodes(conv.parse_anthropic_conversations(claude_conversations(1)), ep_dir)
    conv._stage_episodes(conv.parse_anthropic_conversations(claude_conversations(1, grown=True)), ep_dir)
    assert len(_only(ep_dir).frontmatter["turns"]) == 3
```

  Run: `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_intake.py api/tests/test_intake_turns.py -q -p no:cacheprovider`
  → collection error (`api.routers.intake` does not exist). That is the red.

- [ ] **Step 3: The `turns` sidecar — byte-identical to `2a5ab0b` (R-IA6).** Apply exactly the
  hunk `git show 2a5ab0b -- api/routers/conversations.py` shows (it applies to `c31fb00` as is:
  `cd <worktree> && git show 2a5ab0b -- api/routers/conversations.py | git apply --check && git show
  2a5ab0b -- api/routers/conversations.py | git apply`). If `--check` fails, type it in by hand —
  the result must be character-identical so a later merge with `feat/provenance-viewer` is clean:
  1. Above `def _stage_episodes(` (`:746`), insert the block that begins
     `# G118 slice 2 / R-PB4 — per-message times, kept BESIDE the body.` and defines
     `MAX_TURN_STAMPS = 500`, `_message_line(msg: dict) -> str` (`return f"{msg['role']}:
     {msg['text']}"`) and `_turn_stamps(messages: list[dict], body: str) -> list[dict]` (returns
     `[]` unless `"\n".join(_message_line(m) for m in messages) == body`; one
     `{"offset", "ts", "speaker"}` per message whose `_normalise_import_timestamp(msg.get("timestamp"))`
     is truthy, capped at `MAX_TURN_STAMPS`, `offset += len(line) + 1`).
  2. In `_stage_episodes` (`:798-802`), the four `content_lines` lines become
     `content_str = "\n".join(_message_line(msg) for msg in episode.get("messages", []))`.
  3. In `_write_new_episode`, after the `source_id` block (`:915-917`):

```python
    # G118 slice 2 (R-PB4): each message's time beside the body — outside
    # `content_hash`, and the LAST key so the thread's identity reads first.
    turns = _turn_stamps(episode.get("messages", []), content_str)
    if turns:
        frontmatter["turns"] = turns
```
  4. In `_update_episode_in_place`, after `fm["origin"] = episode["origin"]` (`:941-942`):

```python
    # G118 slice 2 (R-PB4): the grown thread's times replace the old ones; a
    # re-export that lost them drops the key rather than keeping stale offsets.
    turns = _turn_stamps(episode.get("messages", []), content_str)
    fm.pop("turns", None)
    if turns:
        fm["turns"] = turns
```
  Nothing else in `:743-943` changes (R-IA5, D14).

- [ ] **Step 4: `conversations.py` — HTML, Gemini, the wrapper, the shim.**
  - `_parse_chatgpt_html` (`:494-496`): replace the `if not conversations: conversations = [soup]`
    fallback with `if not conversations:` / `return []`, and add to its docstring: "Only ChatGPT's
    legacy export, whose threads sit in `div.conversation` blocks. The old `[soup]` fallback turned
    any page — a bookmarks file, the `chat.html` viewer — into role-less messages dated today
    (Track I D7); a page without those blocks is not a chat export."
  - Replace `parse_gemini_myactivity` (`:568-615`) with:

```python
_GEMINI_VERB = re.compile(r"^(?:Prompted|Asked|Said)[\s ]+")
_GEMINI_TITLE_MAX = 60


def _gemini_title(prompt: str) -> str:
    first = prompt.split("\n", 1)[0].strip()
    if not first:
        return "Gemini activity"
    return first if len(first) <= _GEMINI_TITLE_MAX else first[: _GEMINI_TITLE_MAX - 1].rstrip() + "…"


def parse_gemini_myactivity(html: str) -> list[dict]:
    """Parse a Google Takeout ``Gemini Apps/MyActivity.html`` export (Track I, R-IA9).

    One episode per activity cell. The first content cell reads
    ``Prompted <prompt>``, the activity's rendered timestamp, then Gemini's
    reply; the old parser kept all of it as ONE ``user`` message, so Gemini's
    words were credited to the person, and titled every entry "Gemini
    activity". Now the cell is split at its (last) timestamp line: the prompt
    — minus Google's own verb, which is not the person's words — is ``user``,
    what follows is ``assistant``, and the title is the prompt's first line.

    Each entry also carries ``legacy_hash``: the ``content_hash`` the old
    parser's body would have had. ``api/routers/intake.plan`` counts a legacy
    hash already in the bank as unchanged, so a Takeout re-imported after this
    change duplicates nothing (``_write_new_episode`` never writes the key).
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
            "legacy_hash": (hashlib.sha256(f"user: {legacy_text}".encode()).hexdigest()[:12]
                            if legacy_text else None),
        })

    episodes.sort(key=lambda e: e.get("timestamp") or "")
    return episodes
```
  - Replace `parse_export_bytes` and delete `_parse_zip` (`:650-731`, keep `_IMPORT_FORMAT` and
    `_stamp_origin`):

```python
def parse_export_bytes(content: bytes, filename: str) -> tuple[list[dict], str]:
    """The old 2-tuple, kept for its callers (Track I T2, R-IA7). The one parser
    is ``api.routers.intake.parse_export`` — every zip member it knows, named
    skips, an origin on every path — and this returns its episodes and format.
    Deferred import: ``intake`` imports this module."""
    from api.routers import intake

    parsed = intake.parse_export(content, filename)
    return parsed.episodes, parsed.format
```
  - Replace `upload_conversation` (`:31-87`):

```python
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
```

- [ ] **Step 5: `api/routers/intake.py`** (Task 3 extends `import_bytes` and the import route):

```python
"""One intake for every chat export (Track I T2 — design §9.1, spec decision 13).

Before this module there were two chat-import pipelines that disagreed
(design F3, R7 §1.2). ``POST /conversations/upload`` — the one the ``+`` sheet
and the upload overlay used — rejected zips, sent every ``.html`` (a Gemini
``MyActivity.html`` included) to the ChatGPT scraper, and never stamped
``origin``, so a Claude export imported there read "Unattributed" on the
Sources page and "Claude Code" in the Sleep queue. ``POST /banks/{name}/import``
stamped origins but read ONE zip member. Both are now thin shims over
:func:`import_bytes`, and the app talks to the routes below.

No LLM runs here (CLAUDE.md: nothing at capture time). The sniff stages
nothing — the G71 §4.3 contract ``/sources/upload?preview=true`` already
keeps: Confirm re-posts the same bytes, and nothing is cached between the two.
The vendor parsers stay in ``conversations.py``; this module decides which one
a file needs, and what the file holds besides (R-IA7, R-IA8).
"""
from __future__ import annotations

import hashlib
import io
import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from fastapi import APIRouter, Depends, HTTPException, Query, Response, UploadFile
from loguru import logger
from starlette.concurrency import run_in_threadpool

from api.config import Settings, get_settings
from api.models.schemas import (
    BankImportDateRange,
    IntakeCounts,
    IntakeDelta,
    IntakeIgnored,
    IntakeImportResponse,
    IntakeSniffResponse,
    IntakeTitle,
)
from api.routers import conversations as conv
from api.services import bank_index, bank_registry, media_ingestor

router = APIRouter()

#: Files every export carries that are not conversations (R-IA8). Reported by
#: name in ``ignored[]``; never parsed, never an error.
SKIPPED_MEMBERS: dict[str, str] = {
    "users.json": "account details, not conversations",
    "user.json": "account details, not conversations",
    "message_feedback.json": "ratings you gave replies, not conversations",
    "model_comparisons.json": "model comparisons, not conversations",
    "shared_conversations.json": "links you shared; the chats are in conversations.json",
}
CHAT_HTML = "chat.html"
CHAT_HTML_SKIP = "a viewer page with the same chats as conversations.json"
CHAT_HTML_REASON = ("This looks like ChatGPT's chat.html viewer. "
                    "Drop conversations.json or the whole .zip.")
OTHER_ACTIVITY = "Google activity for another product"
NOT_GEMINI_REASON = ("This is Google activity for another product. "
                     "Export only Gemini Apps from Takeout.")
NOT_A_CHAT_PAGE = "This page isn't a chat export Cicada can read."
EMPTY_ZIP_REASON = "This zip has no conversations Cicada can read."
EMPTY_EXPORT_REASON = "Nothing in this file is a conversation."
MAX_SNIFF_TITLES = 5000

#: ``detect_source`` result -> (wire format, vendor, origin, counts key).
_JSON_SHAPES = {
    "anthropic": ("claude", "claude", "claude-export", "conversations"),
    "anthropic_memories": ("claude_memories", "claude", "claude-export", "memories"),
    "anthropic_projects": ("claude_projects", "claude", "claude-export", "projects"),
    "chatgpt": ("chatgpt", "chatgpt", "chatgpt-export", "conversations"),
}
#: Looked up at call time, so a test's monkeypatch of a parser still lands.
_JSON_PARSERS = {
    "anthropic": lambda data: conv.parse_anthropic_conversations(data),
    "anthropic_memories": lambda data: conv.parse_anthropic_memories(data),
    "anthropic_projects": lambda data: conv.parse_anthropic_projects(data),
    "chatgpt": lambda data: conv.parse_chatgpt_json(data),
}
#: The labels ``/conversations/upload`` always answered with (its ``source``).
_SOURCE_LABELS = {
    "claude": "Claude — Conversations",
    "claude_memories": "Claude — Memories",
    "claude_projects": "Claude — Projects",
    "chatgpt": "ChatGPT — Conversations",
    "gemini": "Gemini — Activity",
}


@dataclass
class ParsedExport:
    """Everything one uploaded file holds, before anything is staged."""

    episodes: list[dict] = field(default_factory=list)
    format: str = "unknown"
    vendors: set[str] = field(default_factory=set)
    origins: set[str] = field(default_factory=set)
    members: list[str] = field(default_factory=list)
    ignored: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def vendor(self) -> str | None:
        return next(iter(self.vendors)) if len(self.vendors) == 1 else None

    @property
    def origin(self) -> str | None:
        return next(iter(self.origins)) if len(self.origins) == 1 else None

    def absorb(self, other: "ParsedExport") -> None:
        self.episodes += other.episodes
        self.members += other.members
        self.ignored += other.ignored
        self.warnings += other.warnings
        self.vendors |= other.vendors
        self.origins |= other.origins
        for key, value in other.counts.items():
            self.counts[key] = self.counts.get(key, 0) + value
        if self.format == "unknown":
            self.format = other.format


def source_label(parsed: ParsedExport) -> str:
    return _SOURCE_LABELS.get(parsed.format, parsed.format)


def parse_export(content: bytes, filename: str) -> ParsedExport:
    """Detect and parse one file — a zip, a JSON export, a Takeout activity page —
    into episodes, every one stamped with its origin (R-IA7). Raises
    ``HTTPException(400, reason)``; the reason is written for the person (the
    panel shows it verbatim)."""
    path = filename or ""
    base = PurePosixPath(path).name
    low = base.lower()
    if low.endswith(".zip"):
        return _parse_zip(content)
    if low in SKIPPED_MEMBERS:
        return ParsedExport(ignored=[{"name": base, "reason": SKIPPED_MEMBERS[low]}])
    if low.endswith((".html", ".htm")):
        return _parse_html(content, path, base)
    if low.endswith(".json") or not low:
        return _parse_json(content, base)
    raise HTTPException(400, "Unsupported file format. Use .json, .html, or .zip")


def _is_activity_page(base: str, text: str) -> bool:
    """The heuristics ``parse_export_bytes`` always used to spot a Takeout page."""
    return "myactivity" in base.lower() or "mdl-typography" in text or "outer-cell" in text


def _is_gemini_activity(path: str, text: str) -> bool:
    """Takeout's "My Activity" is per product. Inside a zip the folder says which
    (``My Activity/Gemini Apps/MyActivity.html``); a page dropped alone is
    Gemini's when it names Gemini — or Bard, its old name — anywhere."""
    lowered = path.lower()
    if "/" in lowered:
        return "gemini" in lowered or "bard" in lowered
    text = text.lower()
    return "gemini" in text or "bard" in text


def _parse_html(content: bytes, path: str, base: str) -> ParsedExport:
    text = content.decode("utf-8", errors="replace")
    if base.lower() == CHAT_HTML:
        raise HTTPException(400, CHAT_HTML_REASON)
    if _is_activity_page(base, text):
        if not _is_gemini_activity(path, text):
            raise HTTPException(400, NOT_GEMINI_REASON)
        episodes = conv.parse_gemini_myactivity(text)
        return ParsedExport(episodes, "gemini", {"gemini"}, {"gemini-export"}, [base],
                            counts={"prompts": len(episodes)})
    episodes = conv._stamp_origin(conv._parse_chatgpt_html(text), "chatgpt-export")
    if not episodes:
        raise HTTPException(400, NOT_A_CHAT_PAGE)
    return ParsedExport(episodes, "chatgpt", {"chatgpt"}, {"chatgpt-export"}, [base],
                        counts={"conversations": len(episodes)})


def _parse_json(content: bytes, base: str) -> ParsedExport:
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise HTTPException(400, f"Failed to parse file: {e}")
    source = conv.detect_source(data, base)
    shape = _JSON_SHAPES.get(source)
    if shape is None:
        raise HTTPException(400, "Unrecognized JSON export format")
    fmt, vendor, origin, key = shape
    episodes = conv._stamp_origin(_JSON_PARSERS[source](data), origin)
    return ParsedExport(episodes, fmt, {vendor}, {origin}, [base or "export.json"],
                        counts={key: len(episodes)})


def _parse_zip(content: bytes) -> ParsedExport:
    """Every member a parser knows, not just the first (design §9.1 item 2; the
    G76-disclosed gap: a Claude zip's memories.json and projects.json were
    dropped because conversations.json won). Named extras go to ``ignored[]``;
    the rest (images, attachments) is one counted warning (R-IA8)."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as e:
        raise HTTPException(400, f"Invalid zip file: {e}")
    out = ParsedExport()
    others = 0
    for info in sorted(zf.infolist(), key=lambda i: i.filename):
        if info.is_dir():
            continue
        member = PurePosixPath(info.filename)
        base, low = member.name, member.name.lower()
        if base.startswith(".") or "__MACOSX" in member.parts:
            continue
        if low in SKIPPED_MEMBERS:
            out.ignored.append({"name": base, "reason": SKIPPED_MEMBERS[low]})
            continue
        if low == CHAT_HTML:
            out.ignored.append({"name": base, "reason": CHAT_HTML_SKIP})
            continue
        if low == "myactivity.html" and "/" in info.filename and not _is_gemini_activity(info.filename, ""):
            out.ignored.append({"name": "/".join(member.parts[-2:]), "reason": OTHER_ACTIVITY})
            continue
        if not low.endswith((".json", ".html", ".htm")):
            others += 1
            continue
        try:
            part = parse_export(zf.read(info), info.filename)
        except HTTPException:
            others += 1
            continue
        out.absorb(part)
    if not out.episodes and not out.members:
        raise HTTPException(400, EMPTY_ZIP_REASON)
    if others == 1:
        out.warnings.append("1 other file in the zip isn't a conversation (images, attachments, settings).")
    elif others:
        out.warnings.append(f"{others} other files in the zip aren't conversations (images, attachments, settings).")
    return out


# --- What staging WOULD do (R-IA5) --------------------------------------------


@dataclass
class StagePlan:
    create: list[dict] = field(default_factory=list)
    update: list[dict] = field(default_factory=list)
    skip: list[dict] = field(default_factory=list)
    #: skipped because the pre-Track-I Gemini parser already staged it (R-IA9)
    legacy: list[dict] = field(default_factory=list)


def _body_hash(episode: dict) -> str:
    body = "\n".join(conv._message_line(m) for m in episode.get("messages", []))
    return hashlib.sha256(body.encode()).hexdigest()[:12]


def plan(episodes: list[dict], memory_path: Path) -> StagePlan:
    """What ``conversations._stage_episodes`` WOULD do to ``memory_path``, writing
    nothing (design §9.1 item 1). Mirrors its decision rule clause for clause —
    ``test_plan_agrees_with_stage_for_new_grown_and_unchanged`` runs both over the
    same fixtures, so a change to one side that misses the other goes red.
    Reads frontmatter through ``bank_index`` (cached by mtime and size), not a
    re-parse per call: a sniff runs on every drop."""
    source_hashes: dict = {}
    known: set[str] = set()
    for f in bank_index.files(memory_path, "episodes"):
        fm = f.frontmatter
        digest = fm.get("content_hash")
        if digest:
            known.add(digest)
        sid = fm.get("source_id")
        if sid:
            source_hashes[sid] = digest
    out = StagePlan()
    for ep in episodes:
        legacy = ep.get("legacy_hash")
        if legacy and legacy in known:
            out.skip.append(ep)
            out.legacy.append(ep)
            continue
        digest = _body_hash(ep)
        sid = ep.get("source_id")
        if sid:
            if sid not in source_hashes:
                out.create.append(ep)
            elif source_hashes[sid] == digest:
                out.skip.append(ep)
                continue
            else:
                out.update.append(ep)
            source_hashes[sid] = digest
            known.add(digest)
            continue
        if digest in known:
            out.skip.append(ep)
            continue
        out.create.append(ep)
        known.add(digest)
    return out


# --- Import -------------------------------------------------------------------


@dataclass
class ImportResult:
    bank: str
    active: bool
    parsed: ParsedExport
    created: int = 0
    updated: int = 0
    skipped: int = 0
    date_from: str | None = None
    date_to: str | None = None


def resolve_target(settings: Settings, bank: str | None, *, scaffold: bool = True) -> tuple[str, Path, bool]:
    """``(name, dir, is_active)`` for ``bank`` (``None`` = the active bank). The
    sniff passes ``scaffold=False``: it must not create a directory either."""
    root = settings.memory_root
    registry = bank_registry.load_registry(root)
    active = registry.get("active", bank_registry.DEFAULT_BANK)
    name = bank or active
    if name not in (registry.get("banks", {}) or {}):
        raise HTTPException(404, f"Unknown bank '{name}'")
    target = bank_registry.bank_dir(root, name)
    if scaffold:
        bank_registry.scaffold_bank(target, git_init=False)
    return name, target, name == active


def date_range(episodes: list[dict]) -> tuple[str | None, str | None]:
    dates = sorted(d for d in (e.get("original_date") for e in episodes) if d)
    return (dates[0], dates[-1]) if dates else (None, None)


def import_bytes(content: bytes, filename: str, settings: Settings, *, bank: str | None = None) -> ImportResult:
    """Parse, plan, stage — the one import every route shares (R-IA10)."""
    name, target, active = resolve_target(settings, bank)
    parsed = parse_export(content, filename)
    date_from, date_to = date_range(parsed.episodes)
    staging = plan(parsed.episodes, target)
    legacy = {id(e) for e in staging.legacy}
    todo = [e for e in parsed.episodes if id(e) not in legacy]
    created, updated, skipped = conv._stage_episodes(todo, target / "episodes")
    if not active and created + updated:
        # G87: staged into a bank Sleep does not read until someone switches to it.
        logger.warning(f"Import into NON-active bank '{name}': {created + updated} episode(s) staged")
    logger.info(f"Intake ({parsed.format}): {created} new, {updated} updated, {skipped + len(legacy)} unchanged")
    return ImportResult(name, active, parsed, created, updated, skipped + len(legacy), date_from, date_to)


def _import_response(result: ImportResult) -> IntakeImportResponse:
    return IntakeImportResponse(
        episodes_staged=result.created,
        episodes_updated=result.updated,
        duplicates_skipped=result.skipped,
        date_range=BankImportDateRange(**{"from": result.date_from, "to": result.date_to}),
        format=result.parsed.format,
        active=result.active,
        bank=result.bank,
        vendor=result.parsed.vendor,
        origin=result.parsed.origin,
        members=result.parsed.members,
        ignored=[IntakeIgnored(**i) for i in result.parsed.ignored],
    )


# --- Sniff (R-IA11) -----------------------------------------------------------


def sniff_bytes(content: bytes, filename: str, settings: Settings, bank: str | None) -> IntakeSniffResponse:
    name = PurePosixPath(filename or "").name
    try:
        parsed = parse_export(content, filename)
    except HTTPException as exc:
        saved = media_ingestor.preview_upload(content, filename)
        if saved.recognized:
            return IntakeSniffResponse(recognized=True, kind="saved", platform=saved.platform,
                                       members=[name], counts=IntakeCounts(items=saved.total),
                                       warnings=saved.warnings)
        return IntakeSniffResponse(recognized=False, reason=str(exc.detail))
    if not parsed.episodes:
        return IntakeSniffResponse(
            recognized=False,
            ignored=[IntakeIgnored(**i) for i in parsed.ignored],
            reason=None if parsed.ignored else EMPTY_EXPORT_REASON,
            warnings=parsed.warnings,
        )
    _, target, _ = resolve_target(settings, bank, scaffold=False)
    staging = plan(parsed.episodes, target)
    date_from, date_to = date_range(parsed.episodes)
    titles = sorted(({"title": str(e.get("title") or "Untitled"), "date": e.get("original_date")}
                     for e in parsed.episodes), key=lambda t: t["date"] or "", reverse=True)
    return IntakeSniffResponse(
        recognized=True,
        kind="chat",
        vendor=parsed.vendor,
        origin=parsed.origin,
        members=parsed.members,
        ignored=[IntakeIgnored(**i) for i in parsed.ignored],
        counts=IntakeCounts(**parsed.counts),
        date_range=BankImportDateRange(**{"from": date_from, "to": date_to}),
        delta=IntakeDelta(new=len(staging.create), grown=len(staging.update), unchanged=len(staging.skip)),
        titles=[IntakeTitle(**t) for t in titles[:MAX_SNIFF_TITLES]],
        titles_truncated=len(titles) > MAX_SNIFF_TITLES,
        warnings=parsed.warnings,
    )


@router.post("/intake/sniff", response_model=IntakeSniffResponse)
async def sniff(
    file: UploadFile,
    bank: str | None = Query(None, max_length=128),
    settings: Settings = Depends(get_settings),
) -> IntakeSniffResponse:
    """What a dropped file IS — vendor, counts, date range, new · grown · already
    here, the titles — staging nothing (G71 §4.3). Titles cross loopback to the
    one panel that asked and are never logged or stored."""
    content = await file.read()
    return await run_in_threadpool(sniff_bytes, content, file.filename or "", settings, bank)


@router.post("/intake/import", response_model=IntakeImportResponse)
async def import_file(
    file: UploadFile,
    response: Response,
    bank: str | None = Query(None, max_length=128),
    settings: Settings = Depends(get_settings),
) -> IntakeImportResponse:
    """Stage a chat export into ``bank`` (default: the active one). Chat only —
    a saved-content file commits through ``/sources/upload`` (R-IA32)."""
    content = await file.read()
    result = await run_in_threadpool(import_bytes, content, file.filename or "", settings, bank=bank)
    return _import_response(result)
```

  (`response` is unused until Task 3 sets `202`; keep it in the signature now so Task 3's diff is
  the job path only.)

- [ ] **Step 6: Schemas** — `api/models/schemas.py`: add two optional fields to
  `BankImportResponse` (after `active`, `:1471`), then the intake models right below it:

```python
    # Track I T2 (R-IA10): the shim now runs the one pipeline, which knows both.
    vendor: Optional[str] = None
    origin: Optional[str] = None


# --- One intake (Track I T2/T2b) ---


class IntakeIgnored(CamelModel):
    """A file the export carries that is not a conversation, said by name."""

    name: str
    reason: str


class IntakeCounts(CamelModel):
    conversations: int = 0
    memories: int = 0
    projects: int = 0
    prompts: int = 0
    items: int = 0


class IntakeDelta(CamelModel):
    """What an import WOULD do, from ``intake.plan`` (G20 made visible first)."""

    new: int = 0
    grown: int = 0
    unchanged: int = 0


class IntakeTitle(CamelModel):
    title: str
    date: Optional[str] = None


class IntakeSniffResponse(CamelModel):
    """``POST /intake/sniff`` — what a dropped file is, staging nothing (G71 §4.3).

    ``recognized`` false with ``reason`` null and ``ignored`` set is a quiet
    skip (a lone ``user.json``); with a ``reason`` it is a file the app should
    name as unreadable, in these words."""

    recognized: bool = False
    kind: Literal["chat", "saved", "unknown"] = "unknown"
    vendor: Optional[str] = None
    origin: Optional[str] = None
    platform: Optional[str] = None
    members: list[str] = []
    ignored: list[IntakeIgnored] = []
    counts: IntakeCounts = Field(default_factory=IntakeCounts)
    date_range: Optional[BankImportDateRange] = None
    delta: IntakeDelta = Field(default_factory=IntakeDelta)
    titles: list[IntakeTitle] = []
    titles_truncated: bool = False
    reason: Optional[str] = None
    warnings: list[str] = []


class IntakeJobRef(CamelModel):
    id: str
    total: int = 0


class IntakeImportResponse(CamelModel):
    """``POST /intake/import``. With ``job`` set (a 202, Track I T2b) the counts
    are what was known at acceptance; poll ``GET /intake/jobs/{id}``."""

    episodes_staged: int = 0
    episodes_updated: int = 0
    duplicates_skipped: int = 0
    date_range: BankImportDateRange = Field(default_factory=BankImportDateRange)
    format: str = "unknown"
    active: bool = True
    bank: str = "default"
    vendor: Optional[str] = None
    origin: Optional[str] = None
    members: list[str] = []
    ignored: list[IntakeIgnored] = []
    job: Optional[IntakeJobRef] = None
```

- [ ] **Step 7: The banks shim** — `api/routers/banks.py`: drop line 28's
  `from api.routers.conversations import _stage_episodes, parse_export_bytes`, import
  `from api.routers import intake`, and replace the body of `import_into_bank` (`:203-254`, keep
  the decorator and signature):

```python
    """Stage a chat export as DATED episodes into bank ``{name}`` (M7).

    Track I T2 (R-IA10): a shim over ``intake.import_bytes`` — the one pipeline,
    so this route gains every zip member, named skips and the Gemini split — kept
    for external callers with its shape, plus ``vendor``/``origin``. G87: the
    ``active`` flag still says when the target is not the bank Sleep reads."""
    content = await file.read()
    logger.info(f"Import into bank '{name}': {file.filename or ''} ({len(content)} bytes)")
    result = await run_in_threadpool(intake.import_bytes, content, file.filename or "", settings, bank=name)
    return BankImportResponse(
        episodes_staged=result.created,
        episodes_updated=result.updated,
        duplicates_skipped=result.skipped,
        date_range=BankImportDateRange(**{"from": result.date_from, "to": result.date_to}),
        format=result.parsed.format,
        active=result.active,
        vendor=result.parsed.vendor,
        origin=result.parsed.origin,
    )
```
  (`hashlib` stays imported only if something else in `banks.py` uses it — `grep -n hashlib
  api/routers/banks.py` and drop the import if the shim was its only user.)

- [ ] **Step 8: Mount** — `api/main.py`: add `intake,` after `inbox,` in the router import list
  (`:13-39`, alphabetical; a sibling track inserts `remote,` after `origins,` — keep the lines apart)
  and `app.include_router(intake.router, tags=["intake"])` directly **after**
  `app.include_router(conversations.router, …)` (`:169`), not at the end of the list where
  `feat/remote-connector` appends.

- [ ] **Step 9: Green.**

```bash
cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_intake.py api/tests/test_intake_turns.py \
  api/tests/test_banks.py api/tests/test_conversations.py -q -p no:cacheprovider
cd <worktree> && api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider 2>&1 | tail -5
```
  → 0 failures. `test_banks.py::test_import_gemini_backdates` still passes unchanged (its fixture's
  cells carry no reply; its text names Gemini).

- [ ] **Step 10: Docs.** `CLAUDE.md` — replace the body of `### 5. Conversation upload` with:

  > **One chat-export pipeline (Track I).** Claude, ChatGPT and Gemini exports — a whole .zip, a folder, or one file — go through `api/routers/intake.py`: every member a parser knows (a Claude zip's conversations, memories and projects), the known extras (`user(s).json`, feedback and comparison files, ChatGPT's `chat.html` viewer) skipped **by name**, the vendor's `origin` stamped on every path, per-message times kept as `turns: [{offset, ts, speaker}]` outside `content_hash`, and re-imports updating grown threads in place (G20) without duplicating. `POST /intake/sniff` previews and stages nothing; `POST /intake/import` stages. `/conversations/upload` (deprecated, `Deprecation: true`) and `/banks/{name}/import` are shims over it.

  and under *Endpoint traps* add: "- `POST /conversations/upload` is a deprecated shim over the one
  intake — new callers use `POST /intake/import`; its `turns` sidecar is a list on imported episodes
  and an **integer count** on Stop-hook episodes, so a reader checks the type." In
  `memory-evolution.md`, append to G12's status cell:

  > **Track I T2 (2026-09-23):** one pipeline — `POST /intake/sniff` (stages nothing) and `POST /intake/import`; `/conversations/upload` (now `Deprecation: true`) and `/banks/{name}/import` are shims over it, so every path stamps the vendor's origin, accepts a zip, and reaches the Gemini parser for a Takeout page. A zip yields every member a parser knows (a Claude zip's memories and projects no longer drop), account and feedback files skipped by name; ChatGPT's `chat.html` viewer is never parsed. The Gemini parser splits prompt from reply and titles each entry by its prompt, with a legacy-hash guard so a Takeout re-imported after the change duplicates nothing. Per-message times ride in `turns: [{offset, ts, speaker}]` outside `content_hash`.

  and to G20's:

  > **Track I T2 (2026-09-23):** the delta is visible BEFORE import — the sniff's `delta{new, grown, unchanged}` comes from a pure `intake.plan()` pinned to `_stage_episodes` by an agreement test.

- [ ] **Step 11: Commit.**

```bash
cd <worktree> && git add api/routers/intake.py api/routers/conversations.py api/routers/banks.py \
  api/models/schemas.py api/main.py api/tests/_intake_fixtures.py api/tests/test_intake.py \
  api/tests/test_intake_turns.py CLAUDE.md docs/goals/memory-evolution.md
git commit -m "feat(intake): one pipeline for every chat export — zips, named skips, origins, Gemini, turns (Track I T2, G12/G20)" \
  -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3 (T2b + origins): Big imports finish in the background, and every import lands under its own name

Design §9.2 (the job counter), design §9.1 item 5 (the Gemini channel, D11), and the repair of
imports that already landed unattributed (D4, R-IA13). Backend plus the app's channel lists, so the
new row ships with its client mapping.

**Files:**
- Create: `api/services/intake_jobs.py`, `api/services/export_origin_migration.py`
- Modify: `api/routers/intake.py` (`import_bytes`, `import_file`, new `GET /intake/jobs/{id}`)
- Modify: `api/models/schemas.py` (`IntakeJobStatus`)
- Modify: `api/services/channel_registry.py:36-45, 234-239`, `api/services/source_overview.py:84-86`
- Modify: `api/services/sleep_cycle.py:1371-1382`, `api/services/bank_migrations.py:30-81`
- Modify (app): `Models/IntegrationCategory.swift:41`, `Views/Capture/ChannelMarks.swift:19-23`, `Views/Capture/ConnectedChannelRow.swift:211, 229, 251`, `Views/Capture/Sheets/AddSourceSheet.swift:125`, `Views/Sources/SourceBlurb.swift:44`
- Test: `api/tests/test_intake_jobs.py`, `api/tests/test_export_origin_migration.py` (new); `api/tests/test_source_channels.py:248, 321`; Swift `ChannelMarkTests`, `IntegrationsViewTests`, `SourceChannelTests`, `FeedChannelStripTests`
- Docs: `CLAUDE.md` (endpoint traps), `memory-evolution.md` (G20)

**Interfaces:** `intake_jobs.start(total, *, already_skipped=0) -> Job`, `get(id)`, `run(job_id,
episodes, episodes_dir, stage, *, batch=BATCH)`, `STAGING_LOCK`, `reset()`; `GET /intake/jobs/{id}
-> IntakeJobStatus {id, total, staged, created, updated, skipped, done, error}`;
`export_origin_migration.backfill_export_origins(memory_path) -> int`, `IMPORTER_ORIGINS`.

- [ ] **Step 1: Failing tests** — `api/tests/test_intake_jobs.py`:

```python
"""Track I T2b — imports that write more than 10 episodes stage in the
background behind a 202 and a job counter (design §9.2, R-IA12)."""
from __future__ import annotations

import json
import threading

from _intake_fixtures import claude_conversations
from api import config
from api.routers import conversations as conv
from api.services import bank_registry, intake_jobs, markdown_parser


def _client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from api import main
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path))
    config.get_settings.cache_clear()
    bank_registry.scaffold_bank(tmp_path, git_init=False)
    intake_jobs.reset()
    return TestClient(main.app)


def _import(client, convs):
    return client.post("/intake/import", files={"file": ("conversations.json", json.dumps(convs).encode(), "application/json")})


def test_a_large_import_answers_202_and_its_job_reaches_done(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    r = _import(client, claude_conversations(50))
    assert r.status_code == 202, r.text
    job = r.json()["job"]
    assert job["total"] == 50 and r.json()["episodesStaged"] == 0
    status = client.get(f"/intake/jobs/{job['id']}").json()
    assert status == {"id": job["id"], "total": 50, "staged": 50, "created": 50, "updated": 0,
                      "skipped": 0, "done": True, "error": None}
    ids = {markdown_parser.parse(p).frontmatter["id"] for p in (tmp_path / "episodes").glob("*.md")}
    assert len(ids) == 50, "batches must mint unique ids (G114 R1)"
    config.get_settings.cache_clear()


def test_a_small_import_stays_synchronous(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    r = _import(client, claude_conversations(3))
    assert r.status_code == 200 and r.json()["job"] is None and r.json()["episodesStaged"] == 3
    config.get_settings.cache_clear()


def test_a_reimport_that_changes_little_stays_synchronous(tmp_path, monkeypatch):
    """The threshold is what WOULD be written (plan), not the file's size."""
    client = _client(tmp_path, monkeypatch)
    assert _import(client, claude_conversations(50)).status_code == 202
    again = _import(client, claude_conversations(50, grown=True))
    assert again.status_code == 200 and (again.json()["episodesUpdated"], again.json()["duplicatesSkipped"]) == (1, 49)
    config.get_settings.cache_clear()


def test_an_unknown_job_is_404(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    assert client.get("/intake/jobs/nope").status_code == 404
    config.get_settings.cache_clear()


def test_a_failing_job_records_its_error_and_still_finishes(tmp_path):
    intake_jobs.reset()
    job = intake_jobs.start(3)

    def boom(_episodes, _dir):
        raise OSError("disk full")

    intake_jobs.run(job.id, [{}, {}, {}], tmp_path / "episodes", boom)
    done = intake_jobs.get(job.id)
    assert done.done is True and done.error == "OSError: disk full" and done.staged == 0


def test_two_jobs_into_one_bank_never_collide(tmp_path):
    """R-IA12: staging is serialised per process; without it both jobs seed ids
    from the same max suffix and `markdown_parser.write` overwrites."""
    intake_jobs.reset()
    ep_dir = tmp_path / "episodes"
    a = conv.parse_anthropic_conversations(claude_conversations(30))
    b = conv.parse_anthropic_conversations(claude_conversations(30))
    for ep in b:
        ep["source_id"] = "other-" + ep["source_id"]
    jobs = [intake_jobs.start(30), intake_jobs.start(30)]
    threads = [threading.Thread(target=intake_jobs.run, args=(j.id, eps, ep_dir, conv._stage_episodes), kwargs={"batch": 7})
               for j, eps in zip(jobs, (a, b))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(list(ep_dir.glob("*.md"))) == 60
```

  `b` has the same bodies as `a` under different `source_id`s, so it goes the G20 create path
  and exercises id minting under contention. `api/tests/test_export_origin_migration.py`:

```python
"""Track I (R-IA13) — the one-shot stamp for chat-export episodes the old
`/conversations/upload` path left without an `origin` (D4)."""
from __future__ import annotations

import subprocess
from pathlib import Path

from api.services import export_origin_migration as mig
from api.services import markdown_parser, sleep_cycle


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True).stdout


def _bank(tmp_path: Path) -> Path:
    repo = tmp_path / "bank"
    (repo / "episodes").mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@cicada.local")
    _git(repo, "config", "user.name", "Cicada Test")
    rows = {
        "ep_2026-02-01_001": {"source": "claude", "processed": True},
        "ep_2026-02-01_002": {"source": "chatgpt", "processed": False},
        "ep_2026-02-01_003": {"source": "claude", "session_id": "3f1c", "processed": True},
        "ep_2026-02-01_004": {"source": "mcp", "processed": True},
        "ep_2026-02-01_005": {"source": "claude", "origin": "claude-export", "processed": True},
    }
    for eid, fm in rows.items():
        markdown_parser.write(repo / "episodes" / f"{eid}.md", {"id": eid, **fm}, "user: alpha-project")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed")
    return repo


def _fm(repo, eid):
    return markdown_parser.parse(repo / "episodes" / f"{eid}.md").frontmatter


def test_only_origin_less_importer_episodes_are_stamped(tmp_path):
    repo = _bank(tmp_path)
    assert mig.backfill_export_origins(repo) == 2
    assert _fm(repo, "ep_2026-02-01_001")["origin"] == "claude-export"
    assert _fm(repo, "ep_2026-02-01_002")["origin"] == "chatgpt-export"
    assert _fm(repo, "ep_2026-02-01_002")["processed"] is False, "nothing re-queues"
    assert "origin" not in _fm(repo, "ep_2026-02-01_003"), "a live conversation is never an import"
    assert "origin" not in _fm(repo, "ep_2026-02-01_004")
    assert markdown_parser.parse(repo / "episodes" / "ep_2026-02-01_001.md").body == "user: alpha-project"


def test_the_commit_is_cicada_authored_and_holds_exactly_the_rewritten_files(tmp_path):
    repo = _bank(tmp_path)
    mig.backfill_export_origins(repo)
    assert "Cicada-Author: cicada" in _git(repo, "log", "-1", "--format=%B")
    assert sorted(_git(repo, "show", "--name-only", "--format=", "HEAD").split()) == [
        "episodes/ep_2026-02-01_001.md", "episodes/ep_2026-02-01_002.md"]


def test_it_runs_once(tmp_path):
    repo = _bank(tmp_path)
    mig.backfill_export_origins(repo)
    head = _git(repo, "rev-parse", "HEAD")
    assert mig.backfill_export_origins(repo) == 0
    assert _git(repo, "rev-parse", "HEAD") == head


def test_sleep_credits_the_importer_to_its_export_not_to_claude_code():
    """D4: `_derive_origin` stamps claims; `source: claude` is only ever the importer."""
    for source, origin in mig.IMPORTER_ORIGINS.items():
        assert sleep_cycle._derive_origin(source) == origin
    assert sleep_cycle._derive_origin("mcp") == "claude-code", "unchanged for live MCP episodes"
```

  In `api/tests/test_source_channels.py`, the two id lists at `:248` and `:321` gain
  `"chat-export:gemini"` right after `"chat-export:chatgpt"`, and add:

```python
def test_a_gemini_takeout_has_its_own_channel(tmp_path):
    """D11 / R-IA14: counted by origin, in prompts."""
    ep_dir = tmp_path / "episodes"
    ep_dir.mkdir(parents=True)
    markdown_parser.write(ep_dir / "ep_2026-02-24_001.md",
                          {"id": "ep_2026-02-24_001", "origin": "gemini-export", "timestamp": "2026-02-24T12:39:02+00:00"},
                          "user: alpha-project")
    chans = {c["id"]: c for c in channel_registry.build_channels(tmp_path, telegram_enabled=False)}
    assert chans["chat-export:gemini"]["count"] == 1 and chans["chat-export:gemini"]["count_noun"] == "prompt"
    assert chans["chat-export:gemini"]["actions"] == ["import"]
```
  (Use the module's existing imports; add `from api.services import channel_registry,
  markdown_parser` if absent.)

  Swift, same commit: `ChannelMarkTests` — the expected map (`:28`) gains
  `"chat-export:gemini": "gemini-export"`; `IntegrationsViewTests:25` gains
  `("chat-export:gemini", .chatAndAgents)`; `SourceChannelTests:75` and `FeedChannelStripTests:39`
  lists gain `"chat-export:gemini"`.

  Run both suites' new tests → red (`intake_jobs`, `export_origin_migration`, the channel do not exist).

- [ ] **Step 2: `api/services/intake_jobs.py`:**

```python
"""Process-local background staging for large imports (Track I T2b — design §9.2).

An export of a few hundred conversations used to stage inside the request, so
the app's panel sat on "Uploading…" with nothing to say. Above
``intake.BACKGROUND_THRESHOLD`` episodes to write, ``POST /intake/import``
answers 202 with a job, stages here in batches through the unchanged
``conversations._stage_episodes`` (each batch re-scans the bank, so G114 ids and
G20 identity stay exact across batches), and ``GET /intake/jobs/{id}`` reports
``{staged, total}`` — a count the app shows only once reported, never
interpolated (design §5.2).

Process-local on purpose (R-IA12): a job is a convenience for the panel that
started it, not state; a backend restart loses the counter, never the episodes
already written. Finished jobs are kept an hour.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from loguru import logger

#: One stage at a time in this process: two overlapping stages into one bank
#: would each seed ids from the same max suffix (G114 R1 is per call), and
#: ``markdown_parser.write`` overwrites on a collision. The sync path takes it too.
STAGING_LOCK = threading.Lock()
BATCH = 50
KEEP_SECONDS = 3600

StageFn = Callable[[list[dict], Path], "tuple[int, int, int]"]


@dataclass
class Job:
    id: str
    total: int
    staged: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    done: bool = False
    error: str | None = None
    finished_at: float | None = None


_jobs: dict[str, Job] = {}
_lock = threading.Lock()


def _prune(now: float) -> None:
    for job_id in [j.id for j in _jobs.values() if j.finished_at and now - j.finished_at > KEEP_SECONDS]:
        _jobs.pop(job_id, None)


def start(total: int, *, already_skipped: int = 0) -> Job:
    with _lock:
        _prune(time.time())
        job = Job(id=uuid.uuid4().hex[:12], total=total, skipped=already_skipped)
        _jobs[job.id] = job
        return job


def get(job_id: str) -> Job | None:
    with _lock:
        return _jobs.get(job_id)


def reset() -> None:
    """Tests only."""
    with _lock:
        _jobs.clear()


def run(job_id: str, episodes: list[dict], episodes_dir: Path, stage: StageFn, *, batch: int = BATCH) -> None:
    job = get(job_id)
    if job is None:
        return
    try:
        with STAGING_LOCK:
            for i in range(0, len(episodes), batch):
                chunk = episodes[i:i + batch]
                created, updated, skipped = stage(chunk, episodes_dir)
                with _lock:
                    job.created += created
                    job.updated += updated
                    job.skipped += skipped
                    job.staged += len(chunk)
    except Exception as exc:  # recorded for the panel, never raised into the server
        logger.error(f"Intake job {job_id} failed: {type(exc).__name__}")
        with _lock:
            job.error = f"{type(exc).__name__}: {exc}"
    finally:
        with _lock:
            job.done = True
            job.finished_at = time.time()
```

- [ ] **Step 3: The job path in `intake.py`.** Add `from api.services import intake_jobs`,
  `BackgroundTasks` to the fastapi import, `IntakeJobRef` and `IntakeJobStatus` to the schema
  import, and:

```python
#: Design §9.2: above this many episodes to WRITE (plan's create + update — not
#: the file's size, so a re-import that changes little stays instant).
BACKGROUND_THRESHOLD = 10
```
  `ImportResult` gains `pending: tuple[list[dict], Path] | None = None`. `import_bytes` gains
  keyword `defer: bool = False` and becomes:

```python
def import_bytes(content: bytes, filename: str, settings: Settings, *, bank: str | None = None,
                 defer: bool = False) -> ImportResult:
    """Parse, plan, stage — the one import every route shares (R-IA10). With
    ``defer`` (only ``POST /intake/import``), a large write is handed back as
    ``pending`` for the job runner instead of staged here (R-IA12)."""
    name, target, active = resolve_target(settings, bank)
    parsed = parse_export(content, filename)
    date_from, date_to = date_range(parsed.episodes)
    staging = plan(parsed.episodes, target)
    legacy = {id(e) for e in staging.legacy}
    todo = [e for e in parsed.episodes if id(e) not in legacy]
    if defer and len(staging.create) + len(staging.update) > BACKGROUND_THRESHOLD:
        return ImportResult(name, active, parsed, 0, 0, len(legacy), date_from, date_to,
                            pending=(todo, target / "episodes"))
    with intake_jobs.STAGING_LOCK:
        created, updated, skipped = conv._stage_episodes(todo, target / "episodes")
    if not active and created + updated:
        # G87: staged into a bank Sleep does not read until someone switches to it.
        logger.warning(f"Import into NON-active bank '{name}': {created + updated} episode(s) staged")
    logger.info(f"Intake ({parsed.format}): {created} new, {updated} updated, {skipped + len(legacy)} unchanged")
    return ImportResult(name, active, parsed, created, updated, skipped + len(legacy), date_from, date_to)
```
  `_import_response(result, job=None)` sets `job=IntakeJobRef(id=job.id, total=job.total) if job
  else None`. The route becomes:

```python
@router.post("/intake/import", response_model=IntakeImportResponse)
async def import_file(
    file: UploadFile,
    response: Response,
    background_tasks: BackgroundTasks,
    bank: str | None = Query(None, max_length=128),
    settings: Settings = Depends(get_settings),
) -> IntakeImportResponse:
    """Stage a chat export into ``bank`` (default: the active one). Chat only —
    a saved-content file commits through ``/sources/upload`` (R-IA32). More than
    ``BACKGROUND_THRESHOLD`` episodes to write: 202 + ``job``."""
    content = await file.read()
    result = await run_in_threadpool(import_bytes, content, file.filename or "", settings, bank=bank, defer=True)
    if result.pending is None:
        return _import_response(result)
    todo, episodes_dir = result.pending
    job = intake_jobs.start(len(todo), already_skipped=result.skipped)
    background_tasks.add_task(intake_jobs.run, job.id, todo, episodes_dir, conv._stage_episodes)
    response.status_code = 202
    return _import_response(result, job=job)


@router.get("/intake/jobs/{job_id}", response_model=IntakeJobStatus)
async def intake_job(job_id: str) -> IntakeJobStatus:
    job = intake_jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "unknown job")
    return IntakeJobStatus(id=job.id, total=job.total, staged=job.staged, created=job.created,
                           updated=job.updated, skipped=job.skipped, done=job.done, error=job.error)
```
  Schema (after `IntakeImportResponse`):

```python
class IntakeJobStatus(CamelModel):
    """``GET /intake/jobs/{id}`` — process-local; gone after a restart or an hour."""

    id: str
    total: int = 0
    staged: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    done: bool = False
    error: Optional[str] = None
```

  The job's `skipped` starts at the legacy count, so its final `skipped` equals the sync path's.

- [ ] **Step 4: The Gemini channel (R-IA14).** `channel_registry.py`: `_NON_CONNECTOR_HEAD` gains
  `"chat-export:gemini",` after `"chat-export:chatgpt",`; the `channels` dict gains, after the
  ChatGPT entry:

```python
        # Track I (R-IA14): a Takeout entry is one prompt and its reply, so the
        # noun is "prompt"; before this row the Gemini card rested on episodes alone.
        "chat-export:gemini": _origin_channel(
            "chat-export:gemini", "Gemini chat export", "gemini-export", by_origin, "prompt"),
```
  `source_overview.py:84-86`: the Gemini `SourceSpec`'s last field becomes `"chat-export:gemini"`
  and its comment "conversations.py — the Gemini Takeout importer; its channel row counts
  `gemini-export` (Track I)". App: `IntegrationCategory.swift:41` → `case "chat-export:claude",
  "chat-export:chatgpt", "chat-export:gemini":`; `ChannelMarks.swift` `allChannelIds` gains
  `"chat-export:gemini"` after chatgpt (and its doc's "14th id" wording becomes "a new id");
  `ConnectedChannelRow.swift:211` and `:229` add `"chat-export:gemini"` to the two chat cases,
  and `origin(forChannel:)` gains `case "chat-export:gemini": "gemini-export"`;
  `AddSourceSheet.swift:125` `.chatExport` → `["chat-export:claude", "chat-export:chatgpt",
  "chat-export:gemini"]` (Task 7 splits the tile); `SourceBlurb.swift` Gemini sentence → "Your
  Gemini prompts and replies from Takeout, one episode per prompt."

- [ ] **Step 5: Origins that stay true (R-IA13).** `sleep_cycle.py:1371-1382` — the map becomes:

```python
# Legacy `source` -> G9 `origin` derivation (origin-and-harness-sync.md §1b).
# Track I (D4): `claude`, `claude_memory`, `claude_project`, `chatgpt` and
# `gemini_export` are written ONLY by the chat importer (conversations.py), so
# they derive to the export — not to `claude-code`, which credited a claude.ai
# export's claims to the Claude Code harness. `export_origin_migration` stamps
# the files themselves; this keeps a not-yet-migrated bank right meanwhile.
_SOURCE_TO_ORIGIN = {
    "claude": "claude-export",
    "claude_memory": "claude-export",
    "claude_project": "claude-export",
    "chatgpt": "chatgpt-export",
    "gemini_export": "gemini-export",
    "mcp": "claude-code",
    "chatgpt-export": "chatgpt-export",
    "claude-export": "claude-export",
    "telegram": "telegram",
    "rss": "rss",
    "bookmark": "bookmark",
}
```
  `api/services/export_origin_migration.py`:

```python
"""Track I (R-IA13) — one-shot, idempotent: stamp ``origin`` on chat-export
episodes written before every import path stamped it.

``POST /conversations/upload`` — the ``+`` sheet's and the upload overlay's path
until Track I — never set ``origin`` (R7 §1.2 defect 1). Those episodes sit in the
Sources page's ``origin:unknown`` bucket ("Unattributed"), and Sleep derived
``claude-code`` for them, stamping a claude.ai export's claims as Claude Code's.
A read-time fallback would have to be taught separately to every reader that keys
on ``origin`` (the overview, ``/origins``, the conversations list, the Sleep
queue); markdown is the source of truth (ruling 3), so the file is fixed once.

Scope, exactly: an episode with NO ``origin``, NO ``session_id`` (a live
conversation is never an import), and a ``source`` only the chat importer writes.
Nothing else is touched — not ``processed``, not the body, not ``content_hash`` —
so nothing re-queues for Sleep and no evidence span moves. Marker-guarded, commit
scoped to exactly the rewritten paths, ``Cicada-Author: cicada`` — the
``decay_migration`` shape. Claims already consolidated keep the origin they were
stamped with (claim origin carries no trust weight; rewriting claims is out of
scope). Never raises.
"""
from __future__ import annotations

import subprocess
from datetime import date
from pathlib import Path

from loguru import logger

from api.services import git_service, markdown_parser

#: The chat importer's own ``source`` values -> the export they came from.
IMPORTER_ORIGINS = {
    "claude": "claude-export",
    "claude_memory": "claude-export",
    "claude_project": "claude-export",
    "chatgpt": "chatgpt-export",
    "gemini_export": "gemini-export",
}
_MARKER = ".export_origins_v1"
TRIGGER = "maintenance/export_origin_backfill"


def backfill_export_origins(memory_path) -> int:
    """Stamp one bank. Returns how many episodes were rewritten."""
    memory_path = Path(memory_path)
    episodes_dir = memory_path / "episodes"
    if not episodes_dir.exists():
        return 0
    marker = memory_path / _MARKER
    if marker.exists():
        return 0
    try:
        written = _rewrite(episodes_dir)
    except Exception as e:
        logger.error(f"Export-origin backfill FAILED — leaving episodes/ untouched: {e}")
        return 0
    if written:
        try:
            _commit(memory_path, written)
        except Exception as e:
            # Files are right on disk; without the marker a later boot retries
            # the commit with 0 further rewrites.
            logger.warning(f"Export-origin backfill commit skipped: {e}")
            return len(written)
    marker.write_text("v1", encoding="utf-8")
    return len(written)


def _rewrite(episodes_dir: Path) -> list[Path]:
    written: list[Path] = []
    for path in sorted(episodes_dir.glob("*.md")):
        try:
            parsed = markdown_parser.parse(path)
        except Exception:
            continue
        fm = parsed.frontmatter or {}
        if not isinstance(fm, dict) or fm.get("origin") or fm.get("session_id"):
            continue
        origin = IMPORTER_ORIGINS.get(str(fm.get("source") or "").strip().lower())
        if not origin:
            continue
        fm["origin"] = origin
        markdown_parser.write(path, fm, parsed.body)
        written.append(path)
    return written


def _commit(memory_path: Path, written: list[Path]) -> None:
    rel = [str(p.relative_to(memory_path)) for p in written]
    subprocess.run(["git", "add", "--", *rel], cwd=str(memory_path), check=True)
    status = subprocess.run(["git", "status", "--porcelain", "--", *rel], cwd=str(memory_path),
                            check=True, capture_output=True, text=True)
    if not status.stdout.strip():
        return
    message = git_service.build_commit_message(
        f"Backfill export origins {date.today().isoformat()}",
        [f"episodes/: {len(rel)} chat-export episode(s) stamped with their origin (trigger: {TRIGGER})"],
        authors=["cicada"],
    )
    subprocess.run(["git", "commit", "-m", message, "--", *rel], cwd=str(memory_path), check=True)
```
  `bank_migrations.py`: import `from api.services.export_origin_migration import
  backfill_export_origins`; after the watermark block call it, log only when non-zero
  (`logger.info(f"Stamped export origin on {originated} imported episode(s)")`), and add
  `"originated": originated` to the returned dict and its docstring.

- [ ] **Step 6: Green** — both suites (`api/tests` full; `swift test`) → 0 failures.

- [ ] **Step 7: Docs.** `CLAUDE.md`, endpoint traps: "- `POST /intake/import` answers **202**
  with `{job}` when more than 10 episodes would be written; poll `GET /intake/jobs/{id}`
  (process-local — gone after a restart or an hour; the episodes are not). One stage runs at a time
  per process." G20's status cell, append: "Imports writing more than 10 episodes stage in
  50-episode batches behind a 202 and `GET /intake/jobs/{id}` (Track I T2b). Episodes the old `+`
  path left without an `origin` are stamped once by `export_origin_migration` (a cicada-authored
  commit), and `_derive_origin` no longer credits the importer's `source: claude` to Claude Code."

- [ ] **Step 8: Commit** — stage the files named in **Files** above, then
  `git commit -m "feat(intake): background staging with a job counter, the Gemini channel, and export origins repaired (Track I T2b, G12/G20)" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"`.

---

### Task 4 (T3): `GET /agents/wiring` — read-only, with the exact commands

Design §9.3 (D12). The app will run these commands after a click (Task 8, D-1 answered yes by
spec decision 14); the backend only reports.

**Files:**
- Create: `api/services/agent_wiring.py`, `api/routers/agents.py`, `api/tests/fixtures/agent_wiring_argv.json`
- Modify: `api/models/schemas.py` (`AgentWiringStep`, `AgentWiringRow`, `AgentWiringResponse`), `api/main.py`
- Test: `api/tests/test_agent_wiring.py` (new)
- Docs: `CLAUDE.md` (Companion App — agent wiring)

**Interfaces:** `agent_wiring.probe(*, home, memory_root, repo=REPO_ROOT, python=None,
runner=None, resolve=base.resolve_binary) -> dict`; `venv_python(repo)`, `hook_command(python,
repo, harness)`; `GET /agents/wiring -> {agents: [{id, installed, binary, recall, autosave,
connect: [{step, display, argv, touches}], detail}], python, repo, memory}`. The shared fixture is
read by Task 8's `AgentWiringCatalogTests`.

- [ ] **Step 1: The shared fixture** — `api/tests/fixtures/agent_wiring_argv.json` (placeholder
  paths, never a real machine's):

```json
{
  "root": "/R/cicada",
  "memory": "/M/memory",
  "cases": [
    {"agent": "claude-code", "step": "mcp",
     "argv": ["claude", "mcp", "add", "cicada", "--scope", "user", "--env", "CICADA_MEMORY_PATH=/M/memory",
              "--", "/R/cicada/api/.venv/bin/python", "/R/cicada/mcp/server.py"]},
    {"agent": "codex", "step": "mcp",
     "argv": ["codex", "mcp", "add", "cicada", "--env", "CICADA_MEMORY_PATH=/M/memory",
              "--", "/R/cicada/api/.venv/bin/python", "/R/cicada/mcp/server.py"]}
  ]
}
```

- [ ] **Step 2: Failing tests** — `api/tests/test_agent_wiring.py`:

```python
"""Track I T3 — GET /agents/wiring is read-only and hands back the exact
commands install.sh would run (design §9.3, R-IA15). Fake HOME, fake binaries,
fake CLI runner: nothing here reads the real ~/.claude or runs a real CLI."""
from __future__ import annotations

import asyncio
import json
import shlex
from pathlib import Path

from api import config
from api.hooks import registry as hook_registry
from api.services import agent_wiring
from api.services.connections import base

REPO = Path("/R/cicada")
PY = "/R/cicada/api/.venv/bin/python"
MEM = Path("/M/memory")


def _runner(rc: int):
    async def run(argv, *, timeout):
        assert timeout == agent_wiring.PROBE_TIMEOUT_S
        return base.CliResult(rc, "", "")
    return run


def _probe(home: Path, rc: int = 1, resolve=lambda name: name if name in ("claude", "codex") else None):
    return asyncio.run(agent_wiring.probe(home=home, memory_root=MEM, repo=REPO, python=PY,
                                          runner=_runner(rc), resolve=resolve))


def _row(data, agent_id):
    return next(a for a in data["agents"] if a["id"] == agent_id)


def test_an_unwired_harness_gets_install_sh_s_exact_commands(tmp_path):
    data = _probe(tmp_path)
    row = _row(data, "claude-code")
    assert (row["installed"], row["recall"], row["autosave"]) == (True, "off", "off")
    [mcp, hook] = row["connect"]
    assert mcp["argv"] == ["claude", "mcp", "add", "cicada", "--scope", "user", "--env",
                           f"CICADA_MEMORY_PATH={MEM}", "--", PY, f"{REPO}/mcp/server.py"]
    assert hook["argv"] == [PY, f"{REPO}/api/hooks/registry.py", "install", "--settings",
                            str(tmp_path / ".claude/settings.json"), "--event", "Stop", "--command",
                            f'"{PY}" "{REPO}/api/hooks/capture.py" --harness claude-code']
    assert hook["touches"] == ["~/.claude/settings.json"] and mcp["touches"] == ["~/.claude.json"]
    for step in row["connect"]:
        assert step["display"] == shlex.join(step["argv"]), "the disclosure can never show one thing and run another"
    assert data["python"] == PY and data["repo"] == str(REPO) and data["memory"] == str(MEM)


def test_a_wired_harness_reads_on_and_offers_nothing(tmp_path):
    settings = tmp_path / ".claude/settings.json"
    hook_registry.install(settings, event="Stop", command=agent_wiring.hook_command(PY, REPO, "claude-code"))
    row = _row(_probe(tmp_path, rc=0), "claude-code")
    assert (row["recall"], row["autosave"], row["connect"]) == ("on", "on", [])


def test_a_stale_hook_is_offered_the_update(tmp_path):
    settings = tmp_path / ".claude/settings.json"
    hook_registry.install(settings, event="Stop", command='"/old/python" "/old/api/hooks/capture.py" --harness claude-code')
    row = _row(_probe(tmp_path, rc=0), "claude-code")
    assert row["autosave"] == "stale" and [s["step"] for s in row["connect"]] == ["hook"]


def test_an_unparseable_settings_file_is_invalid_and_never_touched(tmp_path):
    settings = tmp_path / ".codex/hooks.json"
    settings.parent.mkdir(parents=True)
    settings.write_text("{not json", encoding="utf-8")
    row = _row(_probe(tmp_path), "codex")
    assert row["autosave"] == "invalid", "F8: registry.status alone would have said 'off'"
    assert [s["step"] for s in row["connect"]] == ["mcp"] and "valid JSON" in row["detail"]
    assert settings.read_text(encoding="utf-8") == "{not json"


def test_a_probe_that_times_out_is_unknown_never_off(tmp_path):
    row = _row(_probe(tmp_path, rc=124), "claude-code")
    assert row["recall"] == "unknown" and "mcp" not in [s["step"] for s in row["connect"]]


def test_a_missing_binary_is_not_installed(tmp_path):
    data = _probe(tmp_path, resolve=lambda name: None)
    for row in data["agents"]:
        assert (row["installed"], row["autosave"], row["connect"]) == (False, "n/a", [])


def test_gemini_cli_is_read_only(tmp_path):
    (tmp_path / ".gemini").mkdir()
    (tmp_path / ".gemini/settings.json").write_text(json.dumps({"mcpServers": {"cicada": {}}}), encoding="utf-8")
    row = _row(_probe(tmp_path, resolve=lambda name: name), "gemini-cli")
    assert (row["recall"], row["autosave"], row["connect"]) == ("on", "n/a", [])


def test_the_probe_never_writes(tmp_path):
    settings = tmp_path / ".claude/settings.json"
    hook_registry.install(settings, event="Stop", command="x api/hooks/capture.py")
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    _probe(tmp_path)
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before


def test_no_author_machine_path_is_baked_in():
    source = Path(agent_wiring.__file__).read_text(encoding="utf-8")
    assert "/Users/" not in source and "/home/" not in source, "portability: no author-machine path"


def test_the_shared_argv_fixture_matches():
    """Task 8's AgentWiringCatalogTests reads the same file: the copy-paste snippets
    in Settings → Agents and the commands the app runs cannot drift apart."""
    fixture = json.loads((Path(__file__).parent / "fixtures/agent_wiring_argv.json").read_text())
    data = asyncio.run(agent_wiring.probe(home=Path("/nonexistent-home"), memory_root=Path(fixture["memory"]),
                                          repo=Path(fixture["root"]), python=f"{fixture['root']}/api/.venv/bin/python",
                                          runner=_runner(1), resolve=lambda name: name))
    for case in fixture["cases"]:
        steps = {s["step"]: s["argv"] for s in _row(data, case["agent"])["connect"]}
        assert steps[case["step"]] == case["argv"], case["agent"]


def test_the_route_serves_the_probe(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from api import main

    async def fake_probe(*, home, memory_root):
        return {"agents": [], "python": PY, "repo": str(REPO), "memory": str(memory_root)}

    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path))
    config.get_settings.cache_clear()
    monkeypatch.setattr(agent_wiring, "probe", fake_probe)
    r = TestClient(main.app).get("/agents/wiring")
    assert r.status_code == 200 and r.json()["memory"] == str(tmp_path)
    config.get_settings.cache_clear()
```

  Run → red (`agent_wiring` does not exist).

- [ ] **Step 3: `api/services/agent_wiring.py`:**

```python
"""Read-only: is each agent CLI wired to Cicada? (Track I T3 — design §9.3)

``GET /agents/wiring`` answers two questions per harness — does it *recall* (the
MCP server is registered) and does it *auto-save* (the G105 Stop hook is in its
settings file) — and hands back the exact commands that would wire it, as argv
lists the APP runs after the person's click (spec decision 14, D-1). The backend
never runs them and never writes a harness root: a bearer-authenticated endpoint
that installed a command running on every agent turn would widen the backend's
blast radius (design §1, the rejected ``POST /agents/{id}/enable``).

Computed per request, never persisted (the ``sleep.next_at`` pattern). Each CLI
probe gets 2 s; a timeout is ``unknown``, never ``off`` (verified 2026-09-23:
``claude mcp get`` health-checks the server, ~1.3 s when registered). The only
``~/.claude`` read is ``settings.json`` through ``api/hooks/registry.py`` —
``~/.claude/projects`` is never opened (CLAUDE.md, transcripts rail).
"""
from __future__ import annotations

import asyncio
import json
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from api.hooks import registry as hook_registry
from api.services.connections import base

REPO_ROOT = Path(__file__).resolve().parents[2]
PROBE_TIMEOUT_S = 2.0

Runner = Callable[..., Awaitable[base.CliResult]]


@dataclass(frozen=True)
class Harness:
    id: str
    binary: str
    settings: str             # relative to HOME
    probe: tuple[str, ...]    # exit 0 = registered (verified on the installed CLIs)
    scope: tuple[str, ...]
    config_touch: str


HARNESSES = (
    Harness("claude-code", "claude", ".claude/settings.json", ("mcp", "get", "cicada"),
            ("--scope", "user"), "~/.claude.json"),
    Harness("codex", "codex", ".codex/hooks.json", ("mcp", "get", "cicada", "--json"),
            (), "~/.codex/config.toml"),
)


def venv_python(repo: Path = REPO_ROOT) -> str:
    """install.sh's ``VENV_PY`` (``$API_DIR/.venv/bin/python``), spelled the same
    way, so the hook command below is byte-identical to the one install.sh
    registered — a ``sys.executable`` spelled differently would make
    ``registry.status`` read every correct install as ``stale`` (R-IA15)."""
    candidate = repo / "api" / ".venv" / "bin" / "python"
    return str(candidate) if candidate.exists() else sys.executable


def hook_command(python: str, repo: Path, harness: str) -> str:
    """``install.sh:55``'s ``hook_command``, character for character."""
    return f'"{python}" "{repo}/api/hooks/capture.py" --harness {harness}'


def _step(step: str, argv: list[str], touches: list[str]) -> dict:
    return {"step": step, "display": shlex.join(argv), "argv": argv, "touches": touches}


def _autosave(path: Path, command: str) -> str:
    try:
        hook_registry.load(path)
    except hook_registry.RegistryError:
        return "invalid"
    state = hook_registry.status(path, event="Stop", command=command)
    return {"present": "on", "absent": "off", "stale": "stale"}[state]


async def _harness(h: Harness, *, home: Path, memory_root: Path, repo: Path, python: str,
                   runner: Runner, resolve) -> dict:
    binary = resolve(h.binary)
    if binary is None:
        return {"id": h.id, "installed": False, "binary": None, "recall": "off",
                "autosave": "n/a", "connect": [], "detail": None}
    result = await runner([binary, *h.probe], timeout=PROBE_TIMEOUT_S)
    recall = "on" if result.rc == 0 else ("unknown" if result.rc in (124, 127) else "off")
    settings_path = home / h.settings
    command = hook_command(python, repo, h.id)
    autosave = _autosave(settings_path, command)
    connect: list[dict] = []
    if recall == "off":
        connect.append(_step("mcp", [binary, "mcp", "add", "cicada", *h.scope, "--env",
                                     f"CICADA_MEMORY_PATH={memory_root}", "--", python,
                                     str(repo / "mcp" / "server.py")], [h.config_touch]))
    if autosave in ("off", "stale"):
        connect.append(_step("hook", [python, str(repo / "api" / "hooks" / "registry.py"), "install",
                                      "--settings", str(settings_path), "--event", "Stop",
                                      "--command", command], [f"~/{h.settings}"]))
    detail = None
    if autosave == "invalid":
        detail = f"~/{h.settings} isn't valid JSON, so Cicada won't touch it."
    elif recall == "unknown":
        detail = "Couldn't check in time. Try again."
    return {"id": h.id, "installed": True, "binary": binary, "recall": recall,
            "autosave": autosave, "connect": connect, "detail": detail}


def _gemini_cli(home: Path, resolve) -> dict:
    """Read-only until its CLI registration is verified (R-IA15)."""
    binary = resolve("gemini")
    if binary is None:
        return {"id": "gemini-cli", "installed": False, "binary": None, "recall": "off",
                "autosave": "n/a", "connect": [], "detail": None}
    path = home / ".gemini" / "settings.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        servers = data.get("mcpServers") if isinstance(data, dict) else None
        recall = "on" if isinstance(servers, dict) and "cicada" in servers else "off"
    except (OSError, ValueError):
        recall = "unknown"
    return {"id": "gemini-cli", "installed": True, "binary": binary, "recall": recall,
            "autosave": "n/a", "connect": [], "detail": None}


async def probe(*, home: Path, memory_root: Path, repo: Path = REPO_ROOT, python: str | None = None,
                runner: Runner | None = None, resolve=base.resolve_binary) -> dict:
    python = python or venv_python(repo)
    runner = runner or base.run_cli
    rows = await asyncio.gather(*(
        _harness(h, home=home, memory_root=memory_root, repo=repo, python=python, runner=runner, resolve=resolve)
        for h in HARNESSES))
    return {"agents": [*rows, _gemini_cli(home, resolve)], "python": python,
            "repo": str(repo), "memory": str(memory_root)}
```

- [ ] **Step 4: Route and schemas.** `api/routers/agents.py`:

```python
"""``GET /agents/wiring`` (Track I T3). Request/response, not a sync domain: no
ETag, nothing cached. See ``api/services/agent_wiring.py`` for why it only reads."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends

from api.config import Settings, get_settings
from api.models.schemas import AgentWiringResponse
from api.services import agent_wiring

router = APIRouter()


@router.get("/agents/wiring", response_model=AgentWiringResponse)
async def wiring(settings: Settings = Depends(get_settings)) -> AgentWiringResponse:
    data = await agent_wiring.probe(home=Path.home(), memory_root=settings.memory_root)
    return AgentWiringResponse(**data)
```
  Schemas (end of the intake block):

```python
# --- Agent wiring (Track I T3, read-only) ---


class AgentWiringStep(CamelModel):
    step: Literal["mcp", "hook"]
    display: str
    argv: list[str]
    touches: list[str] = []


class AgentWiringRow(CamelModel):
    id: str
    installed: bool = False
    binary: Optional[str] = None
    recall: Literal["on", "off", "unknown"] = "off"
    autosave: Literal["on", "off", "stale", "invalid", "n/a"] = "n/a"
    connect: list[AgentWiringStep] = []
    detail: Optional[str] = None


class AgentWiringResponse(CamelModel):
    agents: list[AgentWiringRow] = []
    python: str = ""
    repo: str = ""
    memory: str = ""
```
  `api/main.py`: `agents,` first in the router import list; `app.include_router(agents.router,
  tags=["agents"])` right after the `intake` line from Task 2.

- [ ] **Step 5: Green** — `api/tests/test_agent_wiring.py` then the full suite → 0 failures.

- [ ] **Step 6: Docs.** `CLAUDE.md`, Companion App, after the Settings → Integrations paragraph:

  > **Agent wiring (Track I T3/T7).** `GET /agents/wiring` is read-only: per harness it reports *recall* (the MCP server registered — `claude mcp get cicada` / `codex mcp get cicada --json`, 2 s each, a timeout is `unknown`) and *auto-save* (the G105 Stop hook, via `api/hooks/registry.py`; an unparseable settings file is `invalid`, never `off`), plus the exact argv install.sh would run. The **app** runs them, only after the person's click (spec decision 14, D-1), with `CICADA_CAPTURE=off`, behind an allowlist pinned to its own checkout; the backend never writes a harness root.

- [ ] **Step 7: Commit** — `git commit -m "feat(agents): GET /agents/wiring, a read-only probe with the exact commands (Track I T3, G117)" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"`
  after staging exactly the **Files** above.

---

### Task 5 (T4): The shared pieces — `MeadowPill`, `MarkHover`, `FoundRow`, motion, copy

Design §7. Nothing is wired yet; every piece is tested on its own so Tasks 6–8 are renderers.

**Files:**
- Modify: `app/…/Theme/CicadaTheme.swift` (`:139` region + `Dark`/`Light`), `Theme/CicadaMotion.swift` (after `:66` and after `IconHover`), `Theme/LiquidGlass.swift` (after `PrimaryActionButton`, `:137`)
- Create: `app/…/Theme/MeadowPill.swift`, `app/…/Theme/Copy+Intake.swift`, `app/…/Views/Common/FoundRow.swift`
- Test: `ThemeTokenTests.swift`, `CicadaMotionTests.swift`, `CopyConstantsTests.swift` (edited); `MeadowPillTests.swift`, `FoundRowTests.swift` (new)

**Interfaces:** `CicadaTheme.onMeadow`, `.scrim`; `CicadaMotion.revealStagger`, `.revealMaxRows`,
`.markNodDuration`, `.dropVeilDuration`, `.successDuration`, `dropVeil(reduceMotion:)`,
`success(reduceMotion:)`, `reveal(index:reduceMotion:)`; `MarkHover` + `.markHover(hovering:)`;
`LiquidGlass.meadowPillUsesGlass(reduceTransparency:)`, `.meadowInkIsOnMeadow(_:usesGlass:)`,
`.meadowPillStyle()`, `MeadowCapsuleButtonStyle`; `MeadowPill(title:systemImage:isBusy:action:)`;
`FoundMark`, `FoundRowState`, `FoundRow(mark:title:detail:state:disclosure:actionTitle:action:settingsLink:)`;
the `Copy` strings below plus `Copy.intakeLabels`.

- [ ] **Step 1: Failing tests.** `ThemeTokenTests.swift`, add:

```swift
    /// Track I T4 (D-4) — the meadow pill's ink clears AA on the meadow in both
    /// modes: white on the day meadow, night-meadow ink on the night meadow.
    func testTheMeadowPillInkClearsAA() {
        for mode in [AppColorScheme.dark, .light] {
            CicadaTheme.mode = mode
            XCTAssertGreaterThanOrEqual(Self.contrast(CicadaTheme.onMeadow, CicadaTheme.meadow), 4.5, mode.rawValue)
        }
    }

    /// The overlay scrim dims harder in dark, where 0.4 over a near-black window reads as nothing.
    func testTheScrimDimsHarderInDark() {
        CicadaTheme.mode = .dark
        let dark = NSColor(CicadaTheme.scrim).alphaComponent
        CicadaTheme.mode = .light
        let light = NSColor(CicadaTheme.scrim).alphaComponent
        XCTAssertGreaterThan(dark, light)
        XCTAssertEqual(Double(light), 0.35, accuracy: 0.001)
    }
```

  `CicadaMotionTests.swift`, add:

```swift
    func testTheIntakeMotionNamesSitUnderTheBudgetAndVanishUnderReduceMotion() {
        for d in [CicadaMotion.markNodDuration, CicadaMotion.dropVeilDuration, CicadaMotion.successDuration] {
            XCTAssertLessThanOrEqual(d, CicadaMotion.maxDuration)
        }
        XCTAssertEqual(CicadaMotion.revealStagger, 0.04)
        XCTAssertEqual(CicadaMotion.revealMaxRows, 8)
        XCTAssertNil(CicadaMotion.dropVeil(reduceMotion: true))
        XCTAssertNil(CicadaMotion.success(reduceMotion: true))
        XCTAssertNil(CicadaMotion.reveal(index: 3, reduceMotion: true))
        XCTAssertNotNil(CicadaMotion.reveal(index: 30, reduceMotion: false), "capped, never dropped")
    }

    /// `MarkHover` (design §7): a transform-only nod — never a tint — that is a
    /// 1 pt ring under Reduce Motion instead.
    func testTheMarkNodIsATransformAndARingUnderReduceMotion() {
        XCTAssertEqual(MarkHover.rotationKeys, [-5, 3, 0])
        XCTAssertEqual(MarkHover.scaleKeys, [1.08, 1])
        XCTAssertEqual(MarkHover.nextNod(0, entering: true, reduceMotion: false), 1)
        XCTAssertEqual(MarkHover.nextNod(0, entering: true, reduceMotion: true), 0)
        XCTAssertEqual(MarkHover.nextNod(0, entering: false, reduceMotion: false), 0)
        XCTAssertEqual(MarkHover.nextNod(Int.max, entering: true, reduceMotion: false), Int.min, "wraps, never traps")
        XCTAssertTrue(MarkHover.showsRing(hovering: true, reduceMotion: true))
        XCTAssertFalse(MarkHover.showsRing(hovering: true, reduceMotion: false))
    }
```

  `MeadowPillTests.swift` (new):

```swift
import XCTest
@testable import CicadaApp

/// Track I T4 (R-IA16) — the one meadow pill. On the opaque capsule we draw the
/// plate, so the ink is always `onMeadow`; on 26's glass the key-window rule
/// `PrimaryActionInk` learned applies (a non-key window drops the plate).
final class MeadowPillTests: XCTestCase {
    func testTheCapsuleAlwaysCarriesMeadowInk() {
        for state in [ControlActiveState.key, .active, .inactive] {
            XCTAssertTrue(LiquidGlass.meadowInkIsOnMeadow(state, usesGlass: false))
        }
    }

    func testGlassUsesMeadowInkOnlyInAKeyWindow() {
        XCTAssertTrue(LiquidGlass.meadowInkIsOnMeadow(.key, usesGlass: true))
        XCTAssertFalse(LiquidGlass.meadowInkIsOnMeadow(.inactive, usesGlass: true))
    }

    func testReduceTransparencyNeverDrawsGlass() {
        XCTAssertFalse(LiquidGlass.meadowPillUsesGlass(reduceTransparency: true))
    }
}
```

  `FoundRowTests.swift` (new):

```swift
import XCTest
@testable import CicadaApp

/// Track I T4 — a found row's text twin: VoiceOver hears the name, what it is,
/// and its state, in that order (design W4).
final class FoundRowTests: XCTestCase {
    func testTheLabelNamesTheRowItsDetailAndItsState() {
        XCTAssertEqual(FoundRow.accessibilityLabel(title: "Chrome", detail: Copy.foundBrowserDetail, state: .on),
                       "Chrome. \(Copy.foundBrowserDetail). \(Copy.foundOn)")
        XCTAssertEqual(FoundRow.accessibilityLabel(title: "Codex", detail: Copy.foundAgentDetail,
                                                   state: .failed("Couldn't connect")),
                       "Codex. \(Copy.foundAgentDetail). Couldn't connect")
    }

    func testEveryStateSaysSomething() {
        for state: FoundRowState in [.off, .on, .working("Connecting…"), .needsAction("Allow…"), .failed("x")] {
            XCTAssertFalse(FoundRow.stateText(state).isEmpty)
        }
    }

    func testTheDefaultActionTitleFollowsTheState() {
        XCTAssertEqual(FoundRow.defaultActionTitle(.off), Copy.foundTurnOn)
        XCTAssertEqual(FoundRow.defaultActionTitle(.failed("x")), Copy.foundRetry)
        XCTAssertEqual(FoundRow.defaultActionTitle(.needsAction(Copy.foundAllow)), Copy.foundAllow)
        XCTAssertNil(FoundRow.defaultActionTitle(.on))
        XCTAssertNil(FoundRow.defaultActionTitle(.working("…")))
    }
}
```

  `CopyConstantsTests.swift`, add:

```swift
    /// Track I T4 — the intake and found-row labels are short, and "claim" never
    /// reaches onboarding copy (design §7: the word means nothing to a new person).
    func testIntakeLabelsAreShortAndNeverSayClaim() {
        XCTAssertGreaterThan(Copy.intakeLabels.count, 20, "a lint over nothing passes vacuously")
        for label in Copy.intakeLabels {
            XCTAssertLessThanOrEqual(label.count, 60, label)
            XCTAssertFalse(label.lowercased().contains("claim"), label)
        }
        for sentence in Copy.intakeSentences {
            XCTAssertFalse(sentence.lowercased().contains("claim"), sentence)
        }
    }
```

  Run: `swift test --filter "ThemeTokenTests|CicadaMotionTests|MeadowPillTests|FoundRowTests|CopyConstantsTests"`
  → compile failure. Red.

- [ ] **Step 2: Tokens** — `CicadaTheme.swift`, after `onAccent` (`:139`):

```swift
    /// Track I T4 (design §7, D-4) — the ink on the one meadow pill: white on the
    /// day meadow (#37753D, 5.56:1), night-meadow ink on the night meadow
    /// (#7FC98A, ≈ 9.5:1). ThemeTokenTests holds both.
    static var onMeadow: Color { mode == .dark ? Dark.onMeadow : Light.onMeadow }
    /// The dim behind a modal overlay (the intake overlay, the drop veil). Was a
    /// literal `Color.black.opacity(0.4)` in `UploadOverlay`; a token, so dark mode
    /// can dim harder where 0.4 over a near-black window reads as nothing.
    static var scrim: Color { mode == .dark ? Dark.scrim : Light.scrim }
```
  In `enum Dark`: `static let onMeadow = background` and `static let scrim = Color.black.opacity(0.55)`;
  in `enum Light`: `static let onMeadow = Color(hex: 0xFFFFFF)` and `static let scrim = Color.black.opacity(0.35)`.

- [ ] **Step 3: Motion** — `CicadaMotion.swift`, inside `enum CicadaMotion` after `morph(…)`:

```swift
    // Track I T4 (design §7). The drifting cloud reuses `ambientDefaultPeriod` /
    // `ambientMaxAmplitude` — two names for one value is the drift this file
    // exists to stop (R-IA18).
    /// Welcome rows reveal one after another (W1), at most this many staggered.
    static let revealStagger: TimeInterval = 0.04
    static let revealMaxRows = 8
    /// One nod of a brand mark on hover (`MarkHover`).
    static let markNodDuration: TimeInterval = 0.32
    /// The window-wide drop veil fading in (I1).
    static let dropVeilDuration: TimeInterval = 0.18
    /// The one-shot ✓ on a finished import (I6, W9).
    static let successDuration: TimeInterval = 0.4

    static func dropVeil(reduceMotion: Bool) -> Animation? { reduceMotion ? nil : .easeOut(duration: dropVeilDuration) }
    static func success(reduceMotion: Bool) -> Animation? {
        reduceMotion ? nil : .spring(duration: successDuration, bounce: 0.3)
    }
    static func reveal(index: Int, reduceMotion: Bool) -> Animation? {
        reduceMotion ? nil : .easeOut(duration: hoverDuration).delay(revealStagger * Double(min(index, revealMaxRows)))
    }
```
  After `IconHover` (before the `extension View`):

```swift
// MARK: - Mark hover (Track I T4, design §7)

/// A brand mark acknowledges the pointer once: rotate −5° → +3° → 0 and scale
/// 1 → 1.08 → 1 over `markNodDuration`. `symbolEffect` cannot animate a raster,
/// so this is a `keyframeAnimator` on the transform only — it never tints (Track
/// L: a vendor mark is never recoloured). Under Reduce Motion the nod is a 1 pt
/// accent ring while hovered: a cue, not motion. Lives here because its keyframes
/// spell durations, which only this file may (R-IA17). Apply it to the mark view
/// that already clips itself (`LogoImage.platformTile`), so the clip sits inside
/// the transform (design §14 item 4).
struct MarkHover: ViewModifier {
    /// `nil`: follow the mark's own hover; set: a larger target's (a row, a card).
    var hovering: Bool?

    @State private var ownHover = false
    @State private var nods = 0
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    struct Pose: Equatable {
        var rotation: Double = 0
        var scale: CGFloat = 1
    }

    static let rotationKeys: [Double] = [-5, 3, 0]
    static let scaleKeys: [CGFloat] = [1.08, 1]

    /// Pure; tested. Wrapping add, like `IconHover.nextBump`.
    static func nextNod(_ current: Int, entering: Bool, reduceMotion: Bool) -> Int {
        entering && !reduceMotion ? current &+ 1 : current
    }

    static func showsRing(hovering: Bool, reduceMotion: Bool) -> Bool { hovering && reduceMotion }

    private var isHovering: Bool { hovering ?? ownHover }

    func body(content: Content) -> some View {
        content
            .keyframeAnimator(initialValue: Pose(), trigger: nods) { view, pose in
                view.rotationEffect(.degrees(pose.rotation)).scaleEffect(pose.scale)
            } keyframes: { _ in
                KeyframeTrack(\.rotation) {
                    LinearKeyframe(Self.rotationKeys[0], duration: CicadaMotion.markNodDuration * 0.3)
                    LinearKeyframe(Self.rotationKeys[1], duration: CicadaMotion.markNodDuration * 0.35)
                    LinearKeyframe(Self.rotationKeys[2], duration: CicadaMotion.markNodDuration * 0.35)
                }
                KeyframeTrack(\.scale) {
                    LinearKeyframe(Self.scaleKeys[0], duration: CicadaMotion.markNodDuration * 0.5)
                    LinearKeyframe(Self.scaleKeys[1], duration: CicadaMotion.markNodDuration * 0.5)
                }
            }
            .overlay {
                if Self.showsRing(hovering: isHovering, reduceMotion: reduceMotion) {
                    RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall, style: .continuous)
                        .stroke(CicadaTheme.accent, lineWidth: 1)
                }
            }
            .onHover { inside in
                guard hovering == nil else { return }
                ownHover = inside
                nods = Self.nextNod(nods, entering: inside, reduceMotion: reduceMotion)
            }
            .onChange(of: hovering ?? false) { _, now in
                nods = Self.nextNod(nods, entering: now, reduceMotion: reduceMotion)
            }
    }
}
```
  and in the `extension View` at the bottom:

```swift
    /// See `MarkHover` — for brand marks (rasters); glyphs use `iconHover()`.
    func markHover(hovering: Bool? = nil) -> some View { modifier(MarkHover(hovering: hovering)) }
```

- [ ] **Step 4: The meadow pill's style** — `LiquidGlass.swift`. Inside `enum LiquidGlass` add:

```swift
    /// Track I T4 (R-IA16): whether the meadow pill draws system glass (macOS 26,
    /// transparency allowed) or our opaque capsule.
    static func meadowPillUsesGlass(reduceTransparency: Bool) -> Bool {
        #if canImport(SwiftUI, _version: 7.0)
        if #available(macOS 26, *) { return !reduceTransparency }
        return false
        #else
        return false
        #endif
    }

    /// On our capsule we draw the meadow plate, so `onMeadow` always reads; on
    /// glass the plate goes when the window is not key — the rule
    /// `PrimaryActionInk` measured for the accent plate (1.4:1 otherwise).
    static func meadowInkIsOnMeadow(_ state: ControlActiveState, usesGlass: Bool) -> Bool {
        !usesGlass || state == .key
    }
```
  After `PrimaryActionButton`:

```swift
/// The owner's "muted green pill" (design §7, D-4): `.glassProminent` tinted
/// `meadow` on macOS 26, an opaque meadow capsule before — and on 26 under Reduce
/// Transparency. Here, not in `MeadowPill.swift`, because `.glassProminent` lives
/// in this file only (`LiquidGlassLintTests`).
private struct MeadowPillStyleModifier: ViewModifier {
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency

    @ViewBuilder
    func body(content: Content) -> some View {
        #if canImport(SwiftUI, _version: 7.0)
        if #available(macOS 26, *), LiquidGlass.meadowPillUsesGlass(reduceTransparency: reduceTransparency) {
            content.buttonStyle(.glassProminent).tint(CicadaTheme.meadow)
        } else {
            content.buttonStyle(MeadowCapsuleButtonStyle())
        }
        #else
        content.buttonStyle(MeadowCapsuleButtonStyle())
        #endif
    }
}

/// The opaque capsule: meadow fill, a 0.97 press (`CicadaPlainButtonStyle`'s dip).
struct MeadowCapsuleButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var isEnabled
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .padding(.horizontal, CicadaTheme.spacingLG)
            .padding(.vertical, CicadaTheme.spacingSM)
            .background(Capsule().fill(CicadaTheme.meadow.opacity(isEnabled ? 1 : 0.45)))
            .scaleEffect(configuration.isPressed && !reduceMotion ? 0.97 : 1)
            .animation(CicadaMotion.press(reduceMotion: reduceMotion), value: configuration.isPressed)
    }
}
```
  and in the `extension View`: `/// See `MeadowPillStyleModifier` — the intake's Import / Read now only (R-IA16).`
  `func meadowPillStyle() -> some View { modifier(MeadowPillStyleModifier()) }`. The two new
  `#available(macOS 26, *)` lines each sit inside their own `#if canImport(SwiftUI, _version: 7.0)`
  (`testEveryMacOS26GateAlsoHasTheSDKGuard` counts them).

- [ ] **Step 5: `Theme/MeadowPill.swift`:**

```swift
import SwiftUI

/// Track I T4 (design §7, R-IA16) — the one meadow pill: the intake panel's
/// Import and the done card's Read now (part b adds the Welcome's Start).
/// Everywhere else the primary action stays `accent` (`PrimaryActionButton`).
/// It lifts on hover because it starts something.
struct MeadowPill: View {
    let title: String
    var systemImage: String? = nil
    var isBusy = false
    let action: () -> Void

    @Environment(\.controlActiveState) private var activeState
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency

    private var ink: Color {
        let glass = LiquidGlass.meadowPillUsesGlass(reduceTransparency: reduceTransparency)
        return LiquidGlass.meadowInkIsOnMeadow(activeState, usesGlass: glass) ? CicadaTheme.onMeadow : CicadaTheme.textPrimary
    }

    var body: some View {
        Button(action: action) {
            HStack(spacing: CicadaTheme.spacingXS) {
                if isBusy {
                    ProgressView().controlSize(.small)
                } else if let systemImage {
                    Image(systemName: systemImage)
                }
                Text(title).font(CicadaTheme.font(size: 14, weight: .semibold))
            }
            .foregroundStyle(ink)
        }
        .meadowPillStyle()
        .hoverLift(scale: 1.02, lift: 1)
        .disabled(isBusy)
        .accessibilityLabel(title)
    }
}
```

- [ ] **Step 6: `Theme/Copy+Intake.swift`** (R-IA19) — every string Tasks 7 and 8 render:

```swift
import Foundation

/// Track I (part a) — the intake and found-row strings, in their own file so
/// this track and the sibling tracks appending to `Copy.swift` never edit the
/// same lines (R-IA19). Plain words for a person who has never heard "episode"
/// or "claim"; `CopyConstantsTests.testIntakeLabelsAreShortAndNeverSayClaim`
/// holds `intakeLabels` to 60 characters.
extension Copy {
    // MARK: The intake panel (Task 7)
    static let intakeDropTitle = "Drop an export here. The .zip is fine."
    static let intakeDropSubtitle = "Cicada works out what it is. Nothing is read until you say so."
    static let intakeChooseFile = "Choose a file…"
    static let intakeNoExportYet = "Don't have one yet?"
    static let intakeOpenExportPage = "Open export page"
    static let intakeHowToGet = "How to get it"
    static let intakeVeil = "Drop to bring into Cicada"
    static let intakeCancel = "Cancel"
    static let intakeDone = "Done"
    static let intakeReadNow = "Read now"
    static let intakeReadingNowShort = "Reading…"
    static let intakeReadingNow = "Reading now. Follow along on the Sleep page."
    static let intakeChooseWhoReads = "Choose who reads first"
    static let intakeChooseAnother = "Choose another file"
    static let intakeNothingNew = "Nothing new"
    static let intakeNothingNewLine = "Everything in this export is already in your memory."
    static let intakeNothingNewHeadline = "Nothing new came in."
    static let intakeInto = "Into"
    static let intakeActiveSuffix = "(active)"
    static let intakeNewMemory = "New memory…"
    static let intakeNewMemoryPlaceholder = "Name the new memory"
    static let intakeFileMenuItem = "Import…"
    static let intakeMenuBarItem = "Import a file…"
    static let intakeBusy = "Finish the import in progress first."
    static let intakeNothingReadable = "Nothing here is an export Cicada can read."
    static let intakeUnreadable = "Cicada couldn't read this file."
    static let intakeFailed = "The import didn't finish."
    static let intakeFilterPlaceholder = "Filter titles"
    static let intakeFilterLabel = "Filter conversation titles"
    static let emptyStateDropHint = "Or drop a chat export here"

    static func intakeReading(_ names: [String]) -> String {
        names.count == 1 ? "Reading \(names[0])…" : "Reading \(UsageFormat.count(names.count)) files…"
    }
    static func intakeImportButton(_ n: Int) -> String { "Import \(UsageFormat.count(n))" }
    static func intakeSkipped(_ name: String, _ reason: String) -> String { "Skipped: \(name) (\(reason))" }
    static func intakeInactiveBank(_ bank: String) -> String {
        "Imported into “\(bank)”. It isn't your active memory, so it won't be read yet."
    }
    static func intakeSwitchTo(_ bank: String) -> String { "Switch to “\(bank)”" }
    static func whatNextShowsIn(_ name: String) -> String { "They'll show in Sources as “\(name)”" }
    static func intakeCapped(_ n: Int) -> String { "Only the first \(UsageFormat.count(n)) files were read." }
    static func intakeTitlesCapped(_ n: Int) -> String { "Filtering the first \(UsageFormat.count(n)) titles." }
    static func intakeCouldNotCreate(_ name: String) -> String { "Couldn't create “\(name)”." }

    // MARK: Found rows (Tasks 5 and 8)
    static let foundOnThisMac = "On this Mac"
    static let foundTurnOn = "Turn on"
    static let foundOn = "On"
    static let foundOff = "Off"
    static let foundRetry = "Retry"
    static let foundAllow = "Allow…"
    static let foundConnecting = "Connecting…"
    static let foundSavingBookmarks = "Saving bookmarks…"
    static let foundWhatThisChanges = "What this changes"
    static let foundCopyCommands = "Copy commands"
    static let foundAgentDetail = "New sessions are remembered. Past ones stay."
    static let foundBrowserDetail = "Your bookmarks, and new ones as you save them"
    static let foundCursorDetail = "Opens Cursor to add Cicada"
    static let foundClaudeDesktopDetail = "Finish in Settings → Agents"
    static let foundNeedsDiskAccess = "Needs Full Disk Access to read"
    static let foundCheckingApps = "Checking your AI apps…"
    static let foundPastStays = "Past sessions stay where they are. Cicada never reads them."
    static let foundInvalidSettings = "Its settings file isn't valid JSON, so Cicada didn't touch it. Fix it, then Retry."
    static let foundRefused = "Cicada couldn't vouch for these commands, so it didn't run them. Copy them into Terminal instead."
    static let foundBackendDown = "Waiting for Cicada's background service…"

    /// Buttons, titles and one-line captions — held to 60 characters.
    static let intakeLabels: [String] = [
        intakeDropTitle, intakeChooseFile, intakeNoExportYet, intakeOpenExportPage, intakeHowToGet,
        intakeVeil, intakeCancel, intakeDone, intakeReadNow, intakeReadingNowShort, intakeReadingNow,
        intakeChooseWhoReads, intakeChooseAnother, intakeNothingNew, intakeNothingNewLine,
        intakeNothingNewHeadline, intakeInto, intakeNewMemory, intakeNewMemoryPlaceholder,
        intakeFileMenuItem, intakeMenuBarItem, intakeBusy, intakeNothingReadable, intakeUnreadable,
        intakeFailed, intakeFilterPlaceholder, intakeFilterLabel, emptyStateDropHint,
        foundOnThisMac, foundTurnOn, foundOn, foundOff, foundRetry, foundAllow, foundConnecting,
        foundSavingBookmarks, foundWhatThisChanges, foundCopyCommands, foundAgentDetail,
        foundBrowserDetail, foundCursorDetail, foundClaudeDesktopDetail, foundNeedsDiskAccess,
        foundCheckingApps, foundPastStays, foundBackendDown,
    ]
    /// Longer sentences — no length rule, the same vocabulary rule.
    static let intakeSentences: [String] = [intakeDropSubtitle, foundInvalidSettings, foundRefused]
}
```

- [ ] **Step 7: `Views/Common/FoundRow.swift`:**

```swift
import SwiftUI

/// Track I T4 (design §3.8, §7) — one "found on this Mac" row. One component,
/// many hosts: the `+` sheet's On this Mac strip (Task 8), and in part b the
/// Welcome checklist and Home's Getting started. The row renders; it decides
/// nothing — what is on (`LocalInventory`), what would run (`GET /agents/wiring`),
/// what its button does (the host). A dense row: `surfaceHover` fill, never a
/// lift (R9 §3.2); its mark nods through `markHover`.
enum FoundMark: Equatable {
    case logo(String)
    case app(bundleId: String, logo: String?, symbol: String)
}

enum FoundRowState: Equatable {
    case off, on
    case working(String)
    case needsAction(String)
    case failed(String)
}

struct FoundRow: View {
    let mark: FoundMark
    let title: String
    let detail: String
    let state: FoundRowState
    var disclosure: [String] = []
    var actionTitle: String? = nil
    var action: (() -> Void)? = nil
    /// Instead of a button: the one thing to do is in Settings (a plain closure
    /// cannot reliably open that window — see `SettingsSectionLink`).
    var settingsLink: SettingsSection? = nil

    @State private var hovering = false
    @State private var expanded = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    static func stateText(_ state: FoundRowState) -> String {
        switch state {
        case .off: Copy.foundOff
        case .on: Copy.foundOn
        case .working(let text), .needsAction(let text), .failed(let text): text
        }
    }

    static func accessibilityLabel(title: String, detail: String, state: FoundRowState) -> String {
        "\(title). \(detail). \(stateText(state))"
    }

    static func defaultActionTitle(_ state: FoundRowState) -> String? {
        switch state {
        case .off: Copy.foundTurnOn
        case .failed: Copy.foundRetry
        case .needsAction(let label): label
        case .on, .working: nil
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            HStack(spacing: CicadaTheme.spacingSM) {
                markView.markHover(hovering: hovering)
                VStack(alignment: .leading, spacing: 2) {
                    Text(title).font(CicadaTheme.font(size: 13, weight: .semibold)).foregroundStyle(CicadaTheme.textPrimary)
                    Text(detail).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                    if case .failed(let why) = state {
                        Text(why).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.danger)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                Spacer(minLength: CicadaTheme.spacingSM)
                trailing
                if !disclosure.isEmpty {
                    Button { expanded.toggle() } label: {
                        Image(systemName: "chevron.right").rotationEffect(.degrees(expanded ? 90 : 0))
                    }
                    .buttonStyle(.cicadaPlain)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .accessibilityLabel("\(Copy.foundWhatThisChanges), \(title)")
                }
            }
            if expanded {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                    ForEach(disclosure, id: \.self) { line in
                        Text(line).font(CicadaTheme.font(size: 11, design: .monospaced))
                            .foregroundStyle(CicadaTheme.textSecondary).textSelection(.enabled)
                    }
                }
                .padding(.leading, CicadaTheme.scaled(32))
                .transition(.opacity)
            }
        }
        .padding(.vertical, CicadaTheme.spacingXS)
        .padding(.horizontal, CicadaTheme.spacingSM)
        .background(hovering ? CicadaTheme.surfaceHover : .clear,
                    in: RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall, style: .continuous))
        .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
        .animation(CicadaMotion.settle(reduceMotion: reduceMotion), value: expanded)
        .onHover { hovering = $0 }
        .accessibilityElement(children: .contain)
        .accessibilityLabel(Self.accessibilityLabel(title: title, detail: detail, state: state))
    }

    @ViewBuilder private var markView: some View {
        let size = CicadaTheme.scaled(24)
        switch mark {
        case .logo(let name):
            LogoImage.platformTile(name: name, size: size, systemFallback: "app")
        case .app(let bundleId, let logo, let symbol):
            LogoImage.platformTile(name: logo ?? "", bundleId: bundleId, size: size, systemFallback: symbol)
        }
    }

    @ViewBuilder private var trailing: some View {
        switch state {
        case .on:
            Label(Copy.foundOn, systemImage: "checkmark.circle.fill")
                .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.success)
        case .working(let text):
            HStack(spacing: CicadaTheme.spacingXS) {
                ProgressView().controlSize(.small)
                Text(text).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
            }
        case .off, .needsAction, .failed:
            if let settingsLink {
                SettingsSectionLink(section: settingsLink, label: actionTitle ?? Copy.foundClaudeDesktopDetail)
            } else if let title = actionTitle ?? Self.defaultActionTitle(state), let action {
                Button(title, action: action).buttonStyle(.bordered)
            }
        }
    }
}
```
  (`SettingsSectionLink(section:label:)` — `prominent` defaults to `false`,
  `Views/Common/SettingsSectionLink.swift:28-35`.)

- [ ] **Step 8: Green** — `swift build` then `swift test` → 0 failures (the lints included:
  `LiquidGlassLintTests`, `MotionLiteralLintTests`, `FontLiteralLintTests`).

- [ ] **Step 9: Commit** — stage the six Swift sources and five test files named above;
  `git commit -m "feat(meadow): the intake's shared pieces — MeadowPill, MarkHover, FoundRow, motion, copy (Track I T4)" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"`.

---

### Task 6 (T6): The honest pure logic

Design §4.1.4, §4.1.5, §4.1.7, §5.3, §6.2. Lands before Task 7 (R-IA1): the done card's A/B/C
line and its *Read now* gate are these functions. Part b's Welcome and Home consume the rest.

**Files:**
- Create: `app/…/Support/ScheduleHonesty.swift`, `Support/EngineReadiness.swift`, `Support/FoundPolicy.swift`, `Support/OnboardingFlow.swift`, `Support/HomeLayout.swift`
- Modify: `app/…/Theme/Copy+Intake.swift` (the honesty strings)
- Test: `ScheduleHonestyTests.swift`, `EngineReadinessTests.swift`, `FoundPolicyTests.swift`, `OnboardingFlowTests.swift`, `HomeLayoutTests.swift` (new)

**Interfaces:** `ScheduleMode`; `HonestyInputs` (+ `.from(schedule:response:connections:)`);
`ScheduleHonesty.scheduledCanRead/engineLine/whenPhrase/afterImportLine/enabledModes/
offerEveningReminder/preservedMode`; `EngineReadiness` (`.ready(candidate:)`, `.needsChoice`,
`resolve(candidates:connections:preview:)`, `candidateId(forEngine:)`, `hasKey`, `connected`,
`ollamaReady`); `FoundItemID`, `FoundGroup`, `FoundItem`, `FoundPolicy.defaultOn/order/startSummary`;
`OnboardingMode`, `StartStep`, `OnboardingFlow.plan/shouldContinue/canStart/demoSteps`;
`HomeLayout.showsWaitingInToday`. `OnboardingSchedule` (`OnboardingSleepStep.swift:8-37`) stays
until part b retires its host.

- [ ] **Step 1: Failing tests.** `ScheduleHonestyTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// Track I T6 (design §5.3) — every "when will it be read" sentence is a pure
/// function of schedule × the engine previews. Ruling 4 (a scheduled cycle
/// never spends plan quota) is shown, never promised away.
final class ScheduleHonestyTests: XCTestCase {
    private func inputs(manual: String, scheduled: String, mode: ScheduleMode = .manual, hasKey: Bool = false,
                        ollama: Bool = false, claude: Bool = true, hour: Int = 3, interval: Int = 6) -> HonestyInputs {
        HonestyInputs(
            schedule: ScheduleConfig(mode: mode.rawValue, hour: hour, minute: 0, intervalHours: interval),
            preview: SleepEnginePreviews(manual: .init(engine: manual, model: "m", why: "w"),
                                         scheduled: .init(engine: scheduled, model: "m", why: "w")),
            hasKey: hasKey, ollamaReady: ollama, claudeConnected: claude)
    }

    /// The invariant, over every plan and every mode.
    func testRuling4APlanNeverPromisesAScheduledRead() {
        for manual in ["claude-cli", "codex-cli"] {
            for mode in ScheduleMode.allCases {
                let i = inputs(manual: manual, scheduled: "litellm", mode: mode, hasKey: false)
                XCTAssertEqual(ScheduleHonesty.enabledModes(i), [.manual], "\(manual) \(mode)")
                XCTAssertTrue(ScheduleHonesty.offerEveningReminder(i))
                XCTAssertEqual(ScheduleHonesty.afterImportLine(i),
                               mode == .manual ? Copy.afterImportWhenYouAsk : Copy.afterImportPlanWaits)
            }
        }
    }

    func testAKeyOnTheScheduleUnlocksEveryModeAndSaysWhoReads() {
        let i = inputs(manual: "claude-cli", scheduled: "litellm", mode: .daily, hasKey: true)
        XCTAssertEqual(ScheduleHonesty.enabledModes(i), Set(ScheduleMode.allCases))
        XCTAssertFalse(ScheduleHonesty.offerEveningReminder(i))
        XCTAssertEqual(ScheduleHonesty.afterImportLine(i), "Cicada reads these tonight at 3:00, using your API key.")
    }

    func testWhenPhrases() {
        func when(_ mode: ScheduleMode, hour: Int = 3, interval: Int = 6) -> String? {
            ScheduleHonesty.whenPhrase(ScheduleConfig(mode: mode.rawValue, hour: hour, minute: 0, intervalHours: interval))
        }
        XCTAssertEqual(when(.daily), "tonight at 3:00")
        XCTAssertEqual(when(.daily, hour: 21), "tonight at 21:00")
        XCTAssertEqual(when(.daily, hour: 9), "at 9:00")
        XCTAssertEqual(when(.interval, interval: 1), "within the hour")
        XCTAssertEqual(when(.interval), "within 6 hours")
        XCTAssertEqual(when(.afterImport), "a few minutes after imports settle")
        XCTAssertNil(when(.manual))
    }

    func testLineCPrimeWhenNothingCanReadAndNoPlanIsInvolved() {
        let i = inputs(manual: "ollama", scheduled: "ollama", mode: .daily, ollama: false)
        XCTAssertEqual(ScheduleHonesty.afterImportLine(i), Copy.afterImportWaits)
    }

    func testEngineLinesMatchTheDesignTable() {
        XCTAssertEqual(ScheduleHonesty.engineLine(inputs(manual: "claude-cli", scheduled: "litellm", hasKey: true)),
                       Copy.honestyPlanThenKey)
        XCTAssertEqual(ScheduleHonesty.engineLine(inputs(manual: "claude-cli", scheduled: "litellm")),
                       Copy.honestyPlanOnly)
        XCTAssertEqual(ScheduleHonesty.engineLine(inputs(manual: "ollama", scheduled: "ollama", ollama: true)),
                       Copy.honestyOllama)
        XCTAssertEqual(ScheduleHonesty.engineLine(inputs(manual: "litellm", scheduled: "litellm", hasKey: true)),
                       Copy.honestyKey)
        XCTAssertEqual(ScheduleHonesty.engineLine(inputs(manual: "litellm", scheduled: "litellm")),
                       Copy.honestyNothingYet)
    }

    /// Track P R4: onboarding never downgrades an `interval` chosen in Settings.
    func testAnExistingIntervalIsPreservedNeverOffered() {
        XCTAssertEqual(ScheduleHonesty.preservedMode(inputs(manual: "claude-cli", scheduled: "litellm", mode: .interval)),
                       .interval)
        XCTAssertNil(ScheduleHonesty.preservedMode(inputs(manual: "claude-cli", scheduled: "litellm", mode: .daily)))
    }

    func testNoPreviewNeverPromises() {
        var i = inputs(manual: "claude-cli", scheduled: "litellm", mode: .daily, hasKey: true)
        i.preview = nil
        XCTAssertEqual(ScheduleHonesty.enabledModes(i), [.manual])
        XCTAssertEqual(ScheduleHonesty.afterImportLine(i), Copy.afterImportWaits)
    }

    /// F6: the byok candidate is always `connected: true`, even with no key.
    func testTheKeyComesFromConnectionsNotTheByokCandidate() {
        let response = SleepEngineResponse(
            mode: "auto", model: "", disambiguationModel: "", source: "prefs",
            candidates: [SleepEngineCandidate(id: "byok", label: "API key", available: true, connected: true,
                                              models: [], detail: nil)],
            preview: nil)
        let i = HonestyInputs.from(schedule: ScheduleConfig(mode: "manual", hour: 3, minute: 0),
                                   response: response, connections: [])
        XCTAssertFalse(i.hasKey)
    }
}
```

  `EngineReadinessTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// Track I T6 (design §4.1.5) — which engine can actually run the NEXT manual
/// read. `.needsChoice` is what makes Read now ask first.
final class EngineReadinessTests: XCTestCase {
    private func candidate(_ id: String, available: Bool = true, connected: Bool, models: [String] = ["m"]) -> SleepEngineCandidate {
        SleepEngineCandidate(id: id, label: id, available: available, connected: connected, models: models, detail: nil)
    }
    private func connection(kind: String, connected: Bool) -> ConnectionStatus {
        ConnectionStatus(id: "k", label: "k", kind: kind, available: true, connected: connected, plan: nil,
                         planLabel: nil, tier: nil, account: nil, priceUsdMonth: nil, priceNote: nil,
                         billing: "usage", engineRole: nil, detail: nil, login: nil)
    }
    private func preview(_ manual: String) -> SleepEnginePreviews {
        SleepEnginePreviews(manual: .init(engine: manual, model: "m", why: "w"),
                            scheduled: .init(engine: "litellm", model: "m", why: "w"))
    }

    func testAKeylessByokNeedsAChoiceEvenThoughItsCandidateSaysConnected() {
        let byok = candidate("byok", connected: true)
        XCTAssertEqual(EngineReadiness.resolve(candidates: [byok], connections: [], preview: preview("litellm")), .needsChoice)
        XCTAssertEqual(EngineReadiness.resolve(candidates: [byok], connections: [connection(kind: "usage", connected: true)],
                                               preview: preview("litellm")), .ready(candidate: "byok"))
    }

    func testThePlanIsReadyOnlyWhenSignedIn() {
        XCTAssertEqual(EngineReadiness.resolve(candidates: [candidate("agent", connected: true)], connections: [],
                                               preview: preview("claude-cli")), .ready(candidate: "agent"))
        XCTAssertEqual(EngineReadiness.resolve(candidates: [candidate("agent", connected: false)], connections: [],
                                               preview: preview("claude-cli")), .needsChoice)
    }

    func testOllamaNeedsAPulledModel() {
        XCTAssertEqual(EngineReadiness.resolve(candidates: [candidate("local", connected: true)], connections: [],
                                               preview: preview("ollama")), .ready(candidate: "local"))
        XCTAssertEqual(EngineReadiness.resolve(candidates: [candidate("local", connected: true, models: [])], connections: [],
                                               preview: preview("ollama")), .needsChoice)
    }

    func testNoPreviewOrAnUnknownEngineNeedsAChoice() {
        XCTAssertEqual(EngineReadiness.resolve(candidates: [], connections: [], preview: nil), .needsChoice)
        XCTAssertEqual(EngineReadiness.resolve(candidates: [], connections: [], preview: preview("mystery")), .needsChoice)
    }
}
```

  `FoundPolicyTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// Track I T6 (design §4.1.4, D-2) — the visible checklist is the consent:
/// pre-ticked only when it is the person's own intentional act, needs no new
/// permission and opens no other app.
final class FoundPolicyTests: XCTestCase {
    private let en = Locale(identifier: "en_US")
    private func item(_ id: FoundItemID, _ group: FoundGroup, title: String = "X", present: Bool = true,
                      content: FoundItem.Content = .ownIntentionalAct, readiness: FoundItem.Readiness = .ready,
                      opens: Bool = false, count: Int? = nil, noun: String? = nil) -> FoundItem {
        FoundItem(id: id, group: group, title: title, isPresent: present, content: content, readiness: readiness,
                  opensAnotherApp: opens, count: count, countNoun: noun)
    }

    func testOnlyAReadyOwnActThatOpensNothingIsPreTicked() {
        XCTAssertTrue(FoundPolicy.defaultOn(item(.agent("claude-code"), .agents)))
        XCTAssertFalse(FoundPolicy.defaultOn(item(.agent("cursor"), .agents, opens: true)))
        XCTAssertFalse(FoundPolicy.defaultOn(item(.app("wispr"), .notesAndVoice, content: .includesOthers)))
        XCTAssertFalse(FoundPolicy.defaultOn(item(.browser("safari-bookmarks"), .browsers, readiness: .needsPermission)))
        XCTAssertFalse(FoundPolicy.defaultOn(item(.agent("codex"), .agents, readiness: .alreadyOn)))
        XCTAssertFalse(FoundPolicy.defaultOn(item(.agent("codex"), .agents, present: false)))
    }

    func testOrderIsGroupThenTickedThenTitleAndAbsentRowsVanish() {
        let ordered = FoundPolicy.order([
            item(.browser("chrome-bookmarks"), .browsers, title: "Chrome"),
            item(.agent("cursor"), .agents, title: "Cursor", opens: true),
            item(.agent("codex"), .agents, title: "Codex"),
            item(.agent("claude-code"), .agents, title: "Claude Code"),
            item(.agent("gone"), .agents, title: "Gone", present: false),
        ])
        XCTAssertEqual(ordered.map(\.title), ["Claude Code", "Codex", "Cursor", "Chrome"])
    }

    func testTheStartSummaryIsWhatStartDoes() {
        XCTAssertEqual(FoundPolicy.startSummary([], locale: en), Copy.foundStartNothing)
        XCTAssertEqual(FoundPolicy.startSummary([item(.agent("a"), .agents), item(.agent("b"), .agents)], locale: en),
                       "Connects 2 apps.")
        XCTAssertEqual(FoundPolicy.startSummary([item(.agent("a"), .agents),
                                                 item(.browser("chrome-bookmarks"), .browsers, count: 2104, noun: "bookmark")],
                                                locale: en),
                       "Connects 1 app and brings in 2,104 bookmarks.")
        XCTAssertEqual(FoundPolicy.startSummary([item(.browser("safari-bookmarks"), .browsers)], locale: en),
                       "Brings in your bookmarks.")
        XCTAssertEqual(FoundPolicy.startSummary([item(.dropped("export.zip"), .chatHistory, count: 412, noun: "conversation"),
                                                 item(.browser("chrome-bookmarks"), .browsers, count: 1, noun: "bookmark")],
                                                locale: en),
                       "Brings in 1 bookmark and 412 conversations.")
    }
}
```

  `OnboardingFlowTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// Track I T6 (design §4.1.7) — what Start does, in order. The owner save runs
/// alone and first: it is the observer every later write carries (G117 R1).
final class OnboardingFlowTests: XCTestCase {
    func testFirstRunSavesTheOwnerFirstThenTheEngineOnlyIfPicked() {
        XCTAssertEqual(OnboardingFlow.plan(name: "Ada", pickedEngine: nil, ticked: [.agent("claude-code")], mode: .firstRun),
                       [.saveOwner("Ada"), .markOnboarded, .recordGettingStarted([.agent("claude-code")]), .showHome,
                        .turnOn(.agent("claude-code"))])
        XCTAssertEqual(OnboardingFlow.plan(name: " Ada ", pickedEngine: "agent", ticked: [], mode: .firstRun).prefix(2),
                       [.saveOwner("Ada"), .saveEngine("agent")])
    }

    func testSetUpLaterTurnsNothingOn() {
        XCTAssertEqual(OnboardingFlow.plan(name: "Ada", pickedEngine: "agent", ticked: [.agent("codex")], mode: .setUpLater),
                       [.saveOwner("Ada"), .markOnboarded, .recordGettingStarted([]), .showHome])
    }

    func testRerunSavesChangesAndClosesWithoutReMarking() {
        XCTAssertEqual(OnboardingFlow.plan(name: "Ada", pickedEngine: nil, ticked: [.browser("chrome-bookmarks")], mode: .rerun),
                       [.saveOwner("Ada"), .recordGettingStarted([.browser("chrome-bookmarks")]), .close,
                        .turnOn(.browser("chrome-bookmarks"))])
    }

    func testAFailedOwnerSaveStopsEverythingAfterIt() {
        XCTAssertFalse(OnboardingFlow.shouldContinue(after: .saveOwner("Ada"), succeeded: false))
        XCTAssertTrue(OnboardingFlow.shouldContinue(after: .saveOwner("Ada"), succeeded: true))
        XCTAssertTrue(OnboardingFlow.shouldContinue(after: .turnOn(.agent("codex")), succeeded: false),
                      "a row's failure is that row's, never global")
    }

    func testTheNameIsRequired() {
        XCTAssertFalse(OnboardingFlow.canStart(name: "   "))
        XCTAssertTrue(OnboardingFlow.canStart(name: "Ada"))
    }

    func testTheDemoCreatesThenMarksTheLiveBank() {
        XCTAssertEqual(OnboardingFlow.demoSteps, [.createDemoBank, .markOnboarded])
    }
}
```

  `HomeLayoutTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// Track I T6 (design §6.2) — every number appears once: while Getting started
/// shows "Read what came in", TODAY omits its waiting clause.
final class HomeLayoutTests: XCTestCase {
    func testTheWaitingNumberAppearsOnce() {
        XCTAssertFalse(HomeLayout.showsWaitingInToday(gettingStartedVisible: true, hasRunBefore: false))
        XCTAssertTrue(HomeLayout.showsWaitingInToday(gettingStartedVisible: true, hasRunBefore: true))
        XCTAssertTrue(HomeLayout.showsWaitingInToday(gettingStartedVisible: false, hasRunBefore: false))
    }
}
```

  Run `swift test --filter "ScheduleHonesty|EngineReadiness|FoundPolicy|OnboardingFlow|HomeLayout"` → compile failure. Red.

- [ ] **Step 2: Strings** — append to `Theme/Copy+Intake.swift` (inside the extension) and add the
  labels ≤ 60 to `intakeLabels`, the rest to `intakeSentences`:

```swift
    // MARK: Honesty (Task 6, design §5.3) — ruling 4, said out loud
    static let afterImportWhenYouAsk = "Cicada reads these when you ask."
    static let afterImportPlanWaits = "Scheduled reads never use a plan, so these wait until you read them. Read now, or add a key."
    static let afterImportWaits = "Nothing can read these on a schedule yet, so they wait until you read them."
    static func afterImportScheduled(when: String, engine: String) -> String { "Cicada reads these \(when), using \(engine)." }
    static let honestyPlanThenKey = "Your plan reads when you ask. Scheduled reads use your API key."
    static let honestyPlanThenOllama = "Your plan reads when you ask. Scheduled reads run on this Mac."
    static let honestyPlanBoth = "Your plan reads, when you ask and on a schedule."
    static let honestyPlanOnly = "Plans read when you ask. A key or Ollama can also read on a schedule."
    static let honestyOllama = "Reads on this Mac, whenever it runs. Nothing leaves this Mac."
    static let honestyKey = "Your key reads, when you ask and on a schedule. Your provider bills per use."
    static let honestyNothingYet = "Nothing can read yet. Choose who reads before the first read."
    static let foundStartNothing = "Sets your name. You can add sources any time."

    /// The engine as a person says it, inside a sentence ("using your API key").
    /// `Copy.engineLabel` stays the noun for pickers and pills.
    static func engineUse(_ engine: String) -> String {
        switch engine {
        case "claude-cli": "your Claude plan"
        case "codex-cli": "your ChatGPT plan"
        case "ollama": "Ollama on this Mac"
        case "litellm": "your API key"
        default: engineLabel(engine)
        }
    }
```
  `intakeLabels` gains `afterImportWhenYouAsk, honestyPlanThenKey, honestyPlanThenOllama,
  honestyPlanBoth, foundStartNothing`; `intakeSentences` gains `afterImportPlanWaits,
  afterImportWaits, honestyPlanOnly, honestyOllama, honestyKey, honestyNothingYet`.

- [ ] **Step 3: `Support/ScheduleHonesty.swift`:**

```swift
import Foundation

/// The four schedule modes, spelled as the wire spells them (`ScheduleConfig.mode`).
enum ScheduleMode: String, CaseIterable, Hashable {
    case manual, daily, interval
    case afterImport = "after_import"
}

/// Everything a "when will it be read" sentence depends on (design §5.3).
struct HonestyInputs: Equatable {
    var schedule: ScheduleConfig
    var preview: SleepEnginePreviews?
    var hasKey: Bool
    var ollamaReady: Bool
    var claudeConnected: Bool
    var codexConnected: Bool = false

    /// The key comes from `Store.connections`, never from the byok candidate,
    /// which is always `connected: true` even with no key (F6).
    static func from(schedule: ScheduleConfig, response: SleepEngineResponse?,
                     connections: [ConnectionStatus]) -> HonestyInputs {
        let candidates = response?.candidates ?? []
        return HonestyInputs(schedule: schedule, preview: response?.preview,
                             hasKey: EngineReadiness.hasKey(connections),
                             ollamaReady: EngineReadiness.ollamaReady(candidates),
                             claudeConnected: EngineReadiness.connected("agent", candidates),
                             codexConnected: EngineReadiness.connected("codex", candidates))
    }
}

/// Track I T6 (design §5.3) — every sentence about WHEN imported material is
/// read, as a pure function of the schedule and the two engine previews.
/// Replaces `OnboardingSchedule` (part b retires it with its host), which read
/// the schedule alone and so promised a nightly read that a plan-only install
/// can never perform: ruling 4 sends a scheduled cycle to the key rung, and with
/// no key nothing runs (R7 F7). The ruling is shown here, never promised away.
enum ScheduleHonesty {
    static let planEngines: Set<String> = ["claude-cli", "codex-cli"]

    static func canRead(engine: String, _ i: HonestyInputs) -> Bool {
        switch engine {
        case "litellm": i.hasKey
        case "ollama": i.ollamaReady
        case "claude-cli": i.claudeConnected
        case "codex-cli": i.codexConnected
        default: false
        }
    }

    static func scheduledCanRead(_ i: HonestyInputs) -> Bool {
        guard let engine = i.preview?.scheduled.engine else { return false }
        return canRead(engine: engine, i)
    }

    /// The caption under the engine choice (Welcome, chooser).
    static func engineLine(_ i: HonestyInputs) -> String {
        guard let p = i.preview else { return Copy.afterImportWhenYouAsk }
        let manual = p.manual.engine, scheduled = p.scheduled.engine
        if planEngines.contains(manual) {
            if planEngines.contains(scheduled) { return Copy.honestyPlanBoth }
            guard canRead(engine: scheduled, i) else { return Copy.honestyPlanOnly }
            return scheduled == "ollama" ? Copy.honestyPlanThenOllama : Copy.honestyPlanThenKey
        }
        guard canRead(engine: manual, i) else { return Copy.honestyNothingYet }
        switch manual {
        case "ollama": return Copy.honestyOllama
        case "litellm": return Copy.honestyKey
        default: return Copy.afterImportWhenYouAsk
        }
    }

    static func whenPhrase(_ s: ScheduleConfig) -> String? {
        switch ScheduleMode(rawValue: s.mode) {
        case .daily:
            let time = "\(s.hour):" + String(format: "%02d", s.minute)
            return (s.hour < 6 || s.hour >= 18) ? "tonight at \(time)" : "at \(time)"
        case .interval:
            return s.intervalHours == 1 ? "within the hour" : "within \(s.intervalHours) hours"
        case .afterImport:
            return "a few minutes after imports settle"
        case .manual, nil:
            return nil
        }
    }

    /// The done card's line: A (manual), B (a schedule that can read), C (a plan
    /// waiting on ruling 4), C′ (nothing can read on a schedule yet).
    static func afterImportLine(_ i: HonestyInputs) -> String {
        if i.schedule.mode == ScheduleMode.manual.rawValue { return Copy.afterImportWhenYouAsk }
        if scheduledCanRead(i), let p = i.preview, let when = whenPhrase(i.schedule) {
            return Copy.afterImportScheduled(when: when, engine: Copy.engineUse(p.scheduled.engine))
        }
        if let p = i.preview, planEngines.contains(p.manual.engine) { return Copy.afterImportPlanWaits }
        return Copy.afterImportWaits
    }

    /// A mode that cannot deliver is not offered (design §4.2's schedule question).
    static func enabledModes(_ i: HonestyInputs) -> Set<ScheduleMode> {
        scheduledCanRead(i) ? Set(ScheduleMode.allCases) : [.manual]
    }

    /// The evening reminder is offered whenever reads happen only on request.
    static func offerEveningReminder(_ i: HonestyInputs) -> Bool {
        i.schedule.mode == ScheduleMode.manual.rawValue || !scheduledCanRead(i)
    }

    /// Track P R4: an `interval` set in Settings is shown read-only, never downgraded.
    static func preservedMode(_ i: HonestyInputs) -> ScheduleMode? {
        i.schedule.mode == ScheduleMode.interval.rawValue ? .interval : nil
    }
}
```

- [ ] **Step 4: `Support/EngineReadiness.swift`:**

```swift
import Foundation

/// Track I T6 (design §4.1.5) — can the engine the NEXT manual read resolves to
/// actually run? `.ready` rings that card and lets Read now start a cycle;
/// `.needsChoice` makes Read now ask first. An untouched choice stays `auto`
/// (`sleep_engine_prefs.py:104-107`) — this only reads.
enum EngineReadiness: Equatable {
    case ready(candidate: String)
    case needsChoice

    /// `ENGINE_LABELS` id → `GET /sleep/engine` candidate id.
    static func candidateId(forEngine engine: String) -> String? {
        switch engine {
        case "claude-cli": "agent"
        case "codex-cli": "codex"
        case "ollama": "local"
        case "litellm": "byok"
        default: nil
        }
    }

    /// F6: a usage-billed connection that is connected — a real key.
    static func hasKey(_ connections: [ConnectionStatus]) -> Bool {
        connections.contains { $0.kind == "usage" && $0.connected }
    }

    static func connected(_ id: String, _ candidates: [SleepEngineCandidate]) -> Bool {
        candidates.first { $0.id == id }?.connected ?? false
    }

    static func ollamaReady(_ candidates: [SleepEngineCandidate]) -> Bool {
        candidates.first { $0.id == "local" }.map { OllamaGuideState.from(candidate: $0) == .ready } ?? false
    }

    static func resolve(candidates: [SleepEngineCandidate], connections: [ConnectionStatus],
                        preview: SleepEnginePreviews?) -> EngineReadiness {
        guard let engine = preview?.manual.engine, let id = candidateId(forEngine: engine) else { return .needsChoice }
        let canRun: Bool
        switch id {
        case "agent", "codex": canRun = connected(id, candidates)
        case "local": canRun = ollamaReady(candidates)
        default: canRun = hasKey(connections)
        }
        return canRun ? .ready(candidate: id) : .needsChoice
    }
}
```

- [ ] **Step 5: `Support/FoundPolicy.swift`:**

```swift
import Foundation

enum FoundItemID: Hashable {
    case agent(String)      // "claude-code", "codex", "cursor", "claude-desktop"
    case browser(String)    // a BrowserWatch channel id
    case app(String)        // notes & voice (Tracks F/N, part b)
    case dropped(String)    // a file dropped on the Welcome
}

enum FoundGroup: Int, CaseIterable, Comparable {
    case agents, browsers, notesAndVoice, chatHistory
    static func < (a: FoundGroup, b: FoundGroup) -> Bool { a.rawValue < b.rawValue }
}

struct FoundItem: Equatable, Identifiable {
    enum Content: Equatable { case ownIntentionalAct, ownArchive, includesOthers }
    enum Readiness: Equatable { case ready, checking, needsPermission, needsGrant, alreadyOn, failed(String) }

    let id: FoundItemID
    let group: FoundGroup
    let title: String
    let isPresent: Bool
    let content: Content
    let readiness: Readiness
    let opensAnotherApp: Bool
    var count: Int? = nil
    /// Singular; `startSummary` pluralises with `+ "s"`.
    var countNoun: String? = nil
}

/// Track I T6 (design §4.1.4, D-2) — the visible checklist IS the consent. A row
/// is pre-ticked only when it is the person's own intentional act (their agent
/// sessions from now on, bookmarks they saved), needs no new macOS permission and
/// opens no other app; everything else is shown unticked, never hidden.
enum FoundPolicy {
    static func defaultOn(_ i: FoundItem) -> Bool {
        i.isPresent && i.content == .ownIntentionalAct && i.readiness == .ready && !i.opensAnotherApp
    }

    static func order(_ items: [FoundItem]) -> [FoundItem] {
        items.filter(\.isPresent).sorted {
            if $0.group != $1.group { return $0.group < $1.group }
            let (a, b) = (defaultOn($0), defaultOn($1))
            if a != b { return a }
            return $0.title.localizedCaseInsensitiveCompare($1.title) == .orderedAscending
        }
    }

    /// Start's text twin: exactly what Start will do, counted.
    static func startSummary(_ ticked: [FoundItem], locale: Locale = .autoupdatingCurrent) -> String {
        func counted(_ n: Int, _ noun: String) -> String { "\(UsageFormat.count(n, locale: locale)) \(n == 1 ? noun : noun + "s")" }
        let apps = ticked.filter { $0.group == .agents }.count
        var brings: [String] = []
        let browsers = ticked.filter { $0.group == .browsers }
        if !browsers.isEmpty {
            let counts = browsers.compactMap(\.count)
            brings.append(counts.count == browsers.count ? counted(counts.reduce(0, +), "bookmark") : "your bookmarks")
        }
        for item in ticked where item.group == .chatHistory {
            if let n = item.count, let noun = item.countNoun { brings.append(counted(n, noun)) }
        }
        if ticked.contains(where: { $0.group == .notesAndVoice }) { brings.append("your notes") }
        var clauses: [String] = []
        if apps > 0 { clauses.append("Connects \(counted(apps, "app"))") }
        if !brings.isEmpty {
            let list = brings.count == 1 ? brings[0]
                : brings.dropLast().joined(separator: ", ") + " and " + brings[brings.count - 1]
            clauses.append((clauses.isEmpty ? "Brings in " : "brings in ") + list)
        }
        return clauses.isEmpty ? Copy.foundStartNothing : clauses.joined(separator: " and ") + "."
    }
}
```

- [ ] **Step 6: `Support/OnboardingFlow.swift`:**

```swift
import Foundation

enum OnboardingMode: Equatable { case firstRun, setUpLater, rerun }

enum StartStep: Equatable {
    case saveOwner(String)
    case saveEngine(String)
    case markOnboarded
    case recordGettingStarted([FoundItemID])
    case showHome
    case close
    case turnOn(FoundItemID)
    case createDemoBank
}

/// Track I T6 (design §4.1.7) — what Start does, in order, as data. Part b's
/// Welcome executes it. The owner save runs alone and first because it is the
/// observer every later write carries (G117 R1); if it fails, nothing after it
/// runs. Every other step's failure belongs to its own row (§4.1.7 item 6).
/// `markOnboarded` always targets the LIVE bank at execution time
/// (`FirstRunSheet.swift:176-187`'s lesson), which is why the plan names no bank.
enum OnboardingFlow {
    static func canStart(name: String) -> Bool { !name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }

    static func plan(name: String, pickedEngine: String?, ticked: [FoundItemID], mode: OnboardingMode) -> [StartStep] {
        let owner = StartStep.saveOwner(name.trimmingCharacters(in: .whitespacesAndNewlines))
        switch mode {
        case .setUpLater:
            return [owner, .markOnboarded, .recordGettingStarted([]), .showHome]
        case .firstRun:
            return [owner] + (pickedEngine.map { [.saveEngine($0)] } ?? [])
                + [.markOnboarded, .recordGettingStarted(ticked), .showHome] + ticked.map { .turnOn($0) }
        case .rerun:
            return [owner] + (pickedEngine.map { [.saveEngine($0)] } ?? [])
                + [.recordGettingStarted(ticked), .close] + ticked.map { .turnOn($0) }
        }
    }

    static func shouldContinue(after step: StartStep, succeeded: Bool) -> Bool {
        if case .saveOwner = step { return succeeded }
        return true
    }

    static let demoSteps: [StartStep] = [.createDemoBank, .markOnboarded]
}
```

- [ ] **Step 7: `Support/HomeLayout.swift`:**

```swift
import Foundation

/// Track I T6 (design §6.2) — Home's "every number appears once" rule, pure,
/// for part b: while Getting started shows its "Read what came in" row (until
/// the first read), TODAY omits its own waiting clause.
enum HomeLayout {
    static func showsWaitingInToday(gettingStartedVisible: Bool, hasRunBefore: Bool) -> Bool {
        !(gettingStartedVisible && !hasRunBefore)
    }
}
```

- [ ] **Step 8: Green** (`swift test` → 0 failures) and **commit**:
  `git commit -m "feat(onboarding): the honest pure logic — ScheduleHonesty, EngineReadiness, FoundPolicy, OnboardingFlow, HomeLayout (Track I T6, ruling 4)" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"`
  after staging the five sources, `Copy+Intake.swift` and the five test files.

---

### Task 7 (T5): One intake in the app

Design §5 (spec decision 13): every way a file arrives goes sniff → preview → import → a card that
never closes itself. Retires `UploadOverlay` and the Feed's Upload button (D5, D6, D9, D10).

**Files:**
- Create: `app/…/Models/Intake.swift`, `Support/IntakeRouter.swift`, `Support/IntakeSummary.swift`, `Support/DockOpenQueue.swift`, `Views/Intake/IntakePanel.swift`, `Views/Intake/IntakeDoneCard.swift`, `Views/Intake/IntakeOverlay.swift`
- Modify: `Services/APIClient.swift` (append the `IntakeAPI` conformance; delete `uploadFile` `:1999-2031` and `importToBank` `:1150-1180` once `grep -rn "uploadFile(\|importToBank(" Sources` shows no caller)
- Modify: `CicadaApp.swift` (`:47`, `:92-106`, `:162-176`, `:212-221`, `:229-236`), `ContentView.swift` (`:25-35`, `:258-263`), `MenuBarManager.swift` (`:47-60`, `:190-236`), `Views/Graph/GraphView.swift:11-14`
- Modify: `Views/Feed/FeedView.swift` (`:14`, `:55-103`, the empty state at `:242`), `Views/Common/TopBarControls.swift` (`:20-37`, `:77-93`), `Views/Common/EmptyStateView.swift`, `Views/Sources/SourceCardGrid.swift` (empty state `:53`), `Sync/Store.swift:81-90` (doc only)
- Modify: `Views/Capture/Sheets/AddSourceSheet.swift` (`:16-17` and every `switch`, `:309-316`, `:583-584`, delete `:782-792` and `:909-927`, `:881-907`), `ImportFamilies.swift` (`:32`, `:55`, `:97`), `WalkthroughPanel.swift` (`:11-104`), `Theme/Copy.swift:305-322`
- Modify: `app/CicadaApp/bundle.sh:68-84`
- Delete: `app/…/Views/Common/UploadOverlay.swift`
- Test: `IntakeRouterTests.swift`, `IntakePreviewTests.swift`, `IntakeSummaryTests.swift`, `DockOpenQueueTests.swift`, `BundleDocumentTypesTests.swift`, `GraphDropTests.swift` (new); `TopBarControlsTests`, `ImportFamilyTests`, `AddSourceTileTests`, `ImportCatalogTests`, `WalkthroughTests` (edited)
- Docs: `CLAUDE.md` (Navigation, Mascot states), `memory-evolution.md` (G64, G87, G125)

**Interfaces:**
- `protocol IntakeAPI: Sendable` (`sniffIntake(fileURL:bank:)`, `importIntake(fileURL:bank:)`,
  `intakeJob(id:)`, `uploadSaved(fileURL:)`), conformed to by `APIClient`.
- `enum IntakeOrigin` (`welcome, home, windowDrop, dock, menuBar, sleepRoom, emptyState(AppTab),
  feedPlus(ChatVendor?), fileMenu, reminder(ChatVendor), onboardingRow`) with `.host`;
  `IntakeHost`; `IntakePhase`; `IntakeTarget`.
- `@MainActor @Observable final class IntakeRouter`: `phase`, `host`, `isOverlayPresented`,
  `target`, `inFlight`; `attach(store:)`, **`accept(urls:from:)` (public — Track Z's Sleep-room worm
  calls it with `.sleepRoom`)**, `present(from:)`, `retarget(_:)`, `confirm(createBank:)`,
  `cancel()`, `dismiss()`, `finish()`, `commit(urls:from:) async -> IntakeOutcome` (part b's
  Welcome), `static expand(_:)`.
- `IntakeSummary.*`, `DockOpenQueue`, `CicadaAppDelegate`, `IntakePanel(vendor:origin:compact:)`,
  `IntakeOverlay`, `IntakeLayer`, `EmptyStateView(onDropFiles:)`.

- [ ] **Step 1: Wire models** — `Models/Intake.swift`:

```swift
import Foundation

/// Track I T5 — the one intake's wire types, decoded tolerantly: every field has
/// a default, so a response from an older backend (or a 202 carrying only a job)
/// still decodes.
struct IntakeIgnored: Codable, Hashable {
    let name: String
    let reason: String
}

struct IntakeCounts: Codable, Hashable {
    var conversations = 0, memories = 0, projects = 0, prompts = 0, items = 0

    init(conversations: Int = 0, memories: Int = 0, projects: Int = 0, prompts: Int = 0, items: Int = 0) {
        self.conversations = conversations; self.memories = memories; self.projects = projects
        self.prompts = prompts; self.items = items
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        conversations = (try? c.decodeIfPresent(Int.self, forKey: .conversations)) ?? 0
        memories = (try? c.decodeIfPresent(Int.self, forKey: .memories)) ?? 0
        projects = (try? c.decodeIfPresent(Int.self, forKey: .projects)) ?? 0
        prompts = (try? c.decodeIfPresent(Int.self, forKey: .prompts)) ?? 0
        items = (try? c.decodeIfPresent(Int.self, forKey: .items)) ?? 0
    }

    static func + (a: IntakeCounts, b: IntakeCounts) -> IntakeCounts {
        IntakeCounts(conversations: a.conversations + b.conversations, memories: a.memories + b.memories,
                     projects: a.projects + b.projects, prompts: a.prompts + b.prompts, items: a.items + b.items)
    }
}

struct IntakeDelta: Codable, Hashable {
    var new = 0, grown = 0, unchanged = 0

    init(new: Int = 0, grown: Int = 0, unchanged: Int = 0) { self.new = new; self.grown = grown; self.unchanged = unchanged }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        new = (try? c.decodeIfPresent(Int.self, forKey: .new)) ?? 0
        grown = (try? c.decodeIfPresent(Int.self, forKey: .grown)) ?? 0
        unchanged = (try? c.decodeIfPresent(Int.self, forKey: .unchanged)) ?? 0
    }

    static func + (a: IntakeDelta, b: IntakeDelta) -> IntakeDelta {
        IntakeDelta(new: a.new + b.new, grown: a.grown + b.grown, unchanged: a.unchanged + b.unchanged)
    }
}

struct IntakeTitle: Codable, Hashable {
    let title: String
    let date: String?
}

struct IntakeDateRange: Codable, Hashable {
    let from: String?
    let to: String?
}

struct IntakeSniff: Decodable, Equatable {
    var recognized = false
    var kind = "unknown"
    var vendor: String?
    var origin: String?
    var platform: String?
    var members: [String] = []
    var ignored: [IntakeIgnored] = []
    var counts = IntakeCounts()
    var dateRange: IntakeDateRange?
    var delta = IntakeDelta()
    var titles: [IntakeTitle] = []
    var titlesTruncated = false
    var reason: String?
    var warnings: [String] = []

    init(recognized: Bool = false, kind: String = "unknown", vendor: String? = nil, origin: String? = nil,
         platform: String? = nil, members: [String] = [], ignored: [IntakeIgnored] = [],
         counts: IntakeCounts = IntakeCounts(), dateRange: IntakeDateRange? = nil, delta: IntakeDelta = IntakeDelta(),
         titles: [IntakeTitle] = [], titlesTruncated: Bool = false, reason: String? = nil, warnings: [String] = []) {
        self.recognized = recognized; self.kind = kind; self.vendor = vendor; self.origin = origin
        self.platform = platform; self.members = members; self.ignored = ignored; self.counts = counts
        self.dateRange = dateRange; self.delta = delta; self.titles = titles
        self.titlesTruncated = titlesTruncated; self.reason = reason; self.warnings = warnings
    }

    enum CodingKeys: String, CodingKey {
        case recognized, kind, vendor, origin, platform, members, ignored, counts, dateRange, delta
        case titles, titlesTruncated, reason, warnings
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        recognized = (try? c.decodeIfPresent(Bool.self, forKey: .recognized)) ?? false
        kind = (try? c.decodeIfPresent(String.self, forKey: .kind)) ?? "unknown"
        vendor = (try? c.decodeIfPresent(String.self, forKey: .vendor)) ?? nil
        origin = (try? c.decodeIfPresent(String.self, forKey: .origin)) ?? nil
        platform = (try? c.decodeIfPresent(String.self, forKey: .platform)) ?? nil
        members = (try? c.decodeIfPresent([String].self, forKey: .members)) ?? []
        ignored = (try? c.decodeIfPresent([IntakeIgnored].self, forKey: .ignored)) ?? []
        counts = (try? c.decodeIfPresent(IntakeCounts.self, forKey: .counts)) ?? IntakeCounts()
        dateRange = (try? c.decodeIfPresent(IntakeDateRange.self, forKey: .dateRange)) ?? nil
        delta = (try? c.decodeIfPresent(IntakeDelta.self, forKey: .delta)) ?? IntakeDelta()
        titles = (try? c.decodeIfPresent([IntakeTitle].self, forKey: .titles)) ?? []
        titlesTruncated = (try? c.decodeIfPresent(Bool.self, forKey: .titlesTruncated)) ?? false
        reason = (try? c.decodeIfPresent(String.self, forKey: .reason)) ?? nil
        warnings = (try? c.decodeIfPresent([String].self, forKey: .warnings)) ?? []
    }
}

struct IntakeJobRef: Codable, Hashable {
    let id: String
    let total: Int
}

struct IntakeImportResponse: Decodable, Equatable {
    var episodesStaged = 0
    var episodesUpdated = 0
    var duplicatesSkipped = 0
    var dateRange: IntakeDateRange?
    var format = "unknown"
    var active = true
    var bank = "default"
    var vendor: String?
    var origin: String?
    var job: IntakeJobRef?

    init(episodesStaged: Int = 0, episodesUpdated: Int = 0, duplicatesSkipped: Int = 0, dateRange: IntakeDateRange? = nil,
         format: String = "unknown", active: Bool = true, bank: String = "default", vendor: String? = nil,
         origin: String? = nil, job: IntakeJobRef? = nil) {
        self.episodesStaged = episodesStaged; self.episodesUpdated = episodesUpdated
        self.duplicatesSkipped = duplicatesSkipped; self.dateRange = dateRange; self.format = format
        self.active = active; self.bank = bank; self.vendor = vendor; self.origin = origin; self.job = job
    }

    enum CodingKeys: String, CodingKey {
        case episodesStaged, episodesUpdated, duplicatesSkipped, dateRange, format, active, bank, vendor, origin, job
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        episodesStaged = (try? c.decodeIfPresent(Int.self, forKey: .episodesStaged)) ?? 0
        episodesUpdated = (try? c.decodeIfPresent(Int.self, forKey: .episodesUpdated)) ?? 0
        duplicatesSkipped = (try? c.decodeIfPresent(Int.self, forKey: .duplicatesSkipped)) ?? 0
        dateRange = (try? c.decodeIfPresent(IntakeDateRange.self, forKey: .dateRange)) ?? nil
        format = (try? c.decodeIfPresent(String.self, forKey: .format)) ?? "unknown"
        active = (try? c.decodeIfPresent(Bool.self, forKey: .active)) ?? true
        bank = (try? c.decodeIfPresent(String.self, forKey: .bank)) ?? "default"
        vendor = (try? c.decodeIfPresent(String.self, forKey: .vendor)) ?? nil
        origin = (try? c.decodeIfPresent(String.self, forKey: .origin)) ?? nil
        job = (try? c.decodeIfPresent(IntakeJobRef.self, forKey: .job)) ?? nil
    }
}

struct IntakeJobStatus: Decodable, Equatable {
    var id: String
    var total = 0, staged = 0, created = 0, updated = 0, skipped = 0
    var done = false
    var error: String?
}

/// The three chat vendors the intake names, each with its real mark (Track L:
/// `OriginIconography.logoName(for:)` over the export origin).
enum ChatVendor: String, CaseIterable, Identifiable, Hashable {
    case claude, chatgpt, gemini
    var id: String { rawValue }
    var origin: String { "\(rawValue)-export" }
    var channelId: String { "chat-export:\(rawValue)" }
    var title: String {
        switch self {
        case .claude: "Claude"
        case .chatgpt: "ChatGPT"
        case .gemini: "Gemini"
        }
    }
    var walkthrough: WalkthroughVendor {
        switch self {
        case .claude: .claude
        case .chatgpt: .chatgpt
        case .gemini: .gemini
        }
    }
}

/// One file's sniff, or why it could not be sniffed.
struct IntakeFileSniff: Equatable {
    let url: URL
    var sniff: IntakeSniff? = nil
    var error: String? = nil
}
```
  (`IntakeJobStatus` uses the synthesized decoder; the backend always sends every field, and a
  missing `error` decodes as nil because it is optional. Add `enum CodingKeys` only if the compiler
  asks.)

- [ ] **Step 2: Failing tests.** `IntakePreviewTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// Track I T5 — a drop of several files becomes ONE preview. A known extra
/// (`user.json`) is a quiet "Skipped" line; an unreadable file is named with the
/// backend's reason; only a drop with nothing readable fails (design §5.2).
final class IntakePreviewTests: XCTestCase {
    private func url(_ name: String) -> URL { URL(fileURLWithPath: "/tmp/intake/\(name)") }
    private func chat(_ vendor: String, new: Int, grown: Int = 0, same: Int = 0, from: String, to: String) -> IntakeSniff {
        IntakeSniff(recognized: true, kind: "chat", vendor: vendor, origin: "\(vendor)-export",
                    members: ["conversations.json"], counts: IntakeCounts(conversations: new + grown + same),
                    dateRange: IntakeDateRange(from: from, to: to), delta: IntakeDelta(new: new, grown: grown, unchanged: same),
                    titles: [IntakeTitle(title: "t-\(to)", date: to)])
    }

    func testAFolderDropAggregatesAndNamesWhatItSkipped() throws {
        let phase = IntakePreview.aggregate([
            IntakeFileSniff(url: url("conversations.json"),
                            sniff: chat("chatgpt", new: 3, grown: 1, same: 2, from: "2023-03-01", to: "2026-09-01")),
            IntakeFileSniff(url: url("user.json"),
                            sniff: IntakeSniff(ignored: [IntakeIgnored(name: "user.json", reason: "account details, not conversations")])),
            IntakeFileSniff(url: url("chat.html"), sniff: IntakeSniff(reason: "This looks like ChatGPT's chat.html viewer.")),
        ], capped: false)
        guard case .preview(let p) = phase else { return XCTFail("\(phase)") }
        XCTAssertEqual(p.chatFiles.map(\.lastPathComponent), ["conversations.json"])
        XCTAssertEqual(p.vendor, "chatgpt")
        XCTAssertEqual(p.delta, IntakeDelta(new: 3, grown: 1, unchanged: 2))
        XCTAssertEqual(p.importCount, 4, "Import N means new + grew")
        XCTAssertEqual(p.skipped.map(\.name), ["user.json", "chat.html"])
    }

    func testTwoVendorsSumAndKeepTheWiderRange() throws {
        guard case .preview(let p) = IntakePreview.aggregate([
            IntakeFileSniff(url: url("a.zip"), sniff: chat("claude", new: 2, from: "2025-01-01", to: "2025-06-01")),
            IntakeFileSniff(url: url("b.zip"), sniff: chat("chatgpt", new: 5, from: "2024-02-01", to: "2026-01-01")),
        ], capped: false) else { return XCTFail() }
        XCTAssertNil(p.vendor, "two vendors is 'Chat history', never one of them")
        XCTAssertEqual(p.dateFrom, "2024-02-01")
        XCTAssertEqual(p.dateTo, "2026-01-01")
        XCTAssertEqual(p.titles.first?.date, "2026-01-01", "newest first")
    }

    func testNothingReadableFailsWithTheBackendsOwnWords() {
        let phase = IntakePreview.aggregate([
            IntakeFileSniff(url: url("chat.html"), sniff: IntakeSniff(reason: "This looks like ChatGPT's chat.html viewer.")),
        ], capped: false)
        XCTAssertEqual(phase, .failed("This looks like ChatGPT's chat.html viewer."))
    }

    func testSavedContentCountsItsItems() throws {
        guard case .preview(let p) = IntakePreview.aggregate([
            IntakeFileSniff(url: url("bookmarks.html"),
                            sniff: IntakeSniff(recognized: true, kind: "saved", platform: "bookmarks", counts: IntakeCounts(items: 2))),
        ], capped: false) else { return XCTFail() }
        XCTAssertEqual(p.savedFiles.count, 1)
        XCTAssertEqual(p.importCount, 2)
    }

    func testTitlesAreCappedAndSaySo() throws {
        let many = (0..<(IntakePreview.maxTitles + 3)).map { IntakeTitle(title: "t\($0)", date: nil) }
        guard case .preview(let p) = IntakePreview.aggregate([
            IntakeFileSniff(url: url("c.json"), sniff: IntakeSniff(recognized: true, kind: "chat", titles: many)),
        ], capped: true) else { return XCTFail() }
        XCTAssertEqual(p.titles.count, IntakePreview.maxTitles)
        XCTAssertTrue(p.titlesTruncated)
        XCTAssertTrue(p.warnings.contains(Copy.intakeCapped(IntakeRouter.maxFiles)))
    }

    func testANewMemoryAssumesEverythingIsNew() throws {
        guard case .preview(let p) = IntakePreview.aggregate([
            IntakeFileSniff(url: url("c.json"), sniff: chat("claude", new: 1, grown: 2, same: 3, from: "2026-01-01", to: "2026-01-02")),
        ], capped: false) else { return XCTFail() }
        XCTAssertEqual(p.assumingEmptyBank().delta, IntakeDelta(new: 6, grown: 0, unchanged: 0))
    }
}
```

  `IntakeRouterTests.swift`:

```swift
import XCTest
@testable import CicadaApp

final class FakeIntakeAPI: IntakeAPI, @unchecked Sendable {
    var sniffs: [String: IntakeSniff] = [:]
    var sniffDelay: [String: Duration] = [:]
    var imports: [String: IntakeImportResponse] = [:]
    var jobPolls: [IntakeJobStatus] = []
    var importedBanks: [String?] = []
    var failImport: Set<String> = []

    func sniffIntake(fileURL: URL, bank: String?) async throws -> IntakeSniff {
        let name = fileURL.lastPathComponent
        if let delay = sniffDelay[name] { try await Task.sleep(for: delay) }
        return sniffs[name] ?? IntakeSniff(reason: "unknown")
    }

    func importIntake(fileURL: URL, bank: String?) async throws -> IntakeImportResponse {
        importedBanks.append(bank)
        if failImport.contains(fileURL.lastPathComponent) { throw APIError.serverUnreachable }
        return imports[fileURL.lastPathComponent] ?? IntakeImportResponse()
    }

    func intakeJob(id: String) async throws -> IntakeJobStatus { jobPolls.removeFirst() }

    func uploadSaved(fileURL: URL) async throws -> UploadResponse {
        UploadResponse(status: "ok", episodesCreated: 2, duplicatesSkipped: 0, message: "", source: "Bookmarks")
    }
}

/// Track I T5 (design §5.1, R-IA20) — one router for every way a file arrives.
@MainActor
final class IntakeRouterTests: XCTestCase {
    private var dir: URL!

    override func setUp() async throws {
        dir = URL(fileURLWithPath: NSTemporaryDirectory()).appendingPathComponent("intake-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
    }

    override func tearDown() async throws { try? FileManager.default.removeItem(at: dir) }

    private func file(_ name: String) throws -> URL {
        let url = dir.appendingPathComponent(name)
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data("{}".utf8).write(to: url)
        return url
    }

    private func chat(_ vendor: String, new: Int = 1) -> IntakeSniff {
        IntakeSniff(recognized: true, kind: "chat", vendor: vendor, origin: "\(vendor)-export", delta: IntakeDelta(new: new))
    }

    private func eventually(_ what: String, _ condition: @MainActor () -> Bool) async throws {
        let deadline = ContinuousClock.now + .seconds(3)
        while ContinuousClock.now < deadline {
            if condition() { return }
            try await Task.sleep(for: .milliseconds(10))
        }
        XCTFail("timed out: \(what)")
    }

    private func isPreview(_ r: IntakeRouter) -> Bool { if case .preview = r.phase { return true }; return false }
    private func isDone(_ r: IntakeRouter) -> Bool { if case .done = r.phase { return true }; return false }

    func testAStaleSniffNeverLandsOnANewerPreview() async throws {
        let api = FakeIntakeAPI()
        api.sniffs = ["old.json": chat("claude"), "new.json": chat("chatgpt")]
        api.sniffDelay["old.json"] = .milliseconds(250)
        let router = IntakeRouter(api: api)
        router.accept(urls: [try file("old.json")], from: .windowDrop)
        router.accept(urls: [try file("new.json")], from: .windowDrop)
        try await eventually("the newer preview") { self.isPreview(router) }
        try await Task.sleep(for: .milliseconds(400))
        guard case .preview(let p) = router.phase else { return XCTFail("\(router.phase)") }
        XCTAssertEqual(p.vendor, "chatgpt", "the older response must be dropped (H1, hoisted)")
        XCTAssertEqual(router.inFlight, 0)
    }

    func testTheFlagIsTrueExactlyWhileARequestRuns() async throws {
        let store = Store()
        let api = FakeIntakeAPI()
        api.sniffs["c.json"] = chat("claude")
        api.sniffDelay["c.json"] = .milliseconds(150)
        let router = IntakeRouter(api: api)
        router.attach(store: store)
        router.accept(urls: [try file("c.json")], from: .windowDrop)
        try await eventually("a sniff in flight") { store.intakeInFlight }
        try await eventually("the preview") { self.isPreview(router) }
        XCTAssertFalse(store.intakeInFlight, "a preview left open is not an intake landing (R-IA20)")
        XCTAssertEqual(router.inFlight, 0)
    }

    func testTheCounterReturnsToZeroOnFailureAndCancel() async throws {
        let api = FakeIntakeAPI()
        api.sniffDelay["slow.json"] = .milliseconds(150)
        let router = IntakeRouter(api: api)
        router.accept(urls: [try file("slow.json")], from: .windowDrop)
        router.cancel()
        XCTAssertEqual(router.phase, .idle)
        try await eventually("the cancelled request to finish") { router.inFlight == 0 }
        XCTAssertEqual(router.phase, .idle, "a cancelled sniff never lands")
        router.accept(urls: [try file("nothing.json")], from: .windowDrop)
        try await eventually("the failure") { if case .failed = router.phase { true } else { false } }
        XCTAssertEqual(router.inFlight, 0)
    }

    func testTheFeedPlusRendersInPlaceAndEverythingElseRaisesTheOverlay() throws {
        let router = IntakeRouter(api: FakeIntakeAPI())
        router.accept(urls: [try file("a.json")], from: .feedPlus(.claude))
        XCTAssertFalse(router.isOverlayPresented)
        XCTAssertEqual(router.host, .feedPlus)
        router.cancel()
        router.accept(urls: [try file("b.json")], from: .dock)
        XCTAssertTrue(router.isOverlayPresented)
        XCTAssertEqual(router.host, .overlay)
    }

    func testConfirmTwiceImportsOnceAndTheCardNeverClosesItself() async throws {
        let api = FakeIntakeAPI()
        api.sniffs["c.json"] = chat("claude", new: 2)
        api.imports["c.json"] = IntakeImportResponse(episodesStaged: 2, vendor: "claude", origin: "claude-export")
        let router = IntakeRouter(api: api)
        router.accept(urls: [try file("c.json")], from: .windowDrop)
        try await eventually("preview") { self.isPreview(router) }
        router.confirm(createBank: { _ in nil })
        router.confirm(createBank: { _ in nil })
        try await eventually("done") { self.isDone(router) }
        XCTAssertEqual(api.importedBanks.count, 1, "a double tap is one import")
        try await Task.sleep(for: .milliseconds(1_700))
        XCTAssertTrue(isDone(router), "the 1.5 s auto-dismiss is gone with UploadOverlay (design §5.2)")
        router.finish()
        XCTAssertEqual(router.phase, .idle)
        XCTAssertFalse(router.isOverlayPresented)
    }

    func testAJobIsFollowedAndItsCountIsOnlyEverWhatItReported() async throws {
        let api = FakeIntakeAPI()
        api.sniffs["big.json"] = chat("claude", new: 50)
        api.imports["big.json"] = IntakeImportResponse(vendor: "claude", job: IntakeJobRef(id: "j1", total: 50))
        api.jobPolls = [IntakeJobStatus(id: "j1", total: 50, staged: 25),
                        IntakeJobStatus(id: "j1", total: 50, staged: 50, created: 50, done: true)]
        let router = IntakeRouter(api: api, sleep: { _ in })
        router.accept(urls: [try file("big.json")], from: .windowDrop)
        try await eventually("preview") { self.isPreview(router) }
        router.confirm(createBank: { _ in nil })
        try await eventually("done") { self.isDone(router) }
        guard case .done(let outcome) = router.phase else { return XCTFail() }
        XCTAssertEqual(outcome.created, 50)
        XCTAssertEqual(router.inFlight, 0)
    }

    func testANewMemoryIsCreatedBeforeTheImportAndTargeted() async throws {
        let api = FakeIntakeAPI()
        api.sniffs["c.json"] = chat("claude")
        let router = IntakeRouter(api: api)
        router.accept(urls: [try file("c.json")], from: .windowDrop)
        try await eventually("preview") { self.isPreview(router) }
        router.retarget(.newBank("alpha-project"))
        router.confirm(createBank: { name in name == "alpha-project" ? "alpha-project" : nil })
        try await eventually("done") { self.isDone(router) }
        XCTAssertEqual(api.importedBanks, ["alpha-project"])
    }

    func testADropWhileImportingIsRefused() async throws {
        let api = FakeIntakeAPI()
        api.sniffs["c.json"] = chat("claude")
        api.imports["c.json"] = IntakeImportResponse(job: IntakeJobRef(id: "j", total: 1))
        api.jobPolls = [IntakeJobStatus(id: "j", total: 1, staged: 1, created: 1, done: true)]
        let gate = AsyncStream<Void>.makeStream()
        let router = IntakeRouter(api: api, sleep: { _ in for await _ in gate.stream { break } })
        router.accept(urls: [try file("c.json")], from: .windowDrop)
        try await eventually("preview") { self.isPreview(router) }
        router.confirm(createBank: { _ in nil })
        try await eventually("importing") { if case .importing = router.phase { true } else { false } }
        router.accept(urls: [try file("d.json")], from: .windowDrop)
        if case .importing = router.phase {} else { XCTFail("a second drop replaced an import in flight") }
        gate.continuation.yield()
        try await eventually("done") { self.isDone(router) }
    }

    func testCommitImportsWithoutAPreview() async throws {
        let api = FakeIntakeAPI()
        api.imports["c.json"] = IntakeImportResponse(episodesStaged: 3, vendor: "claude")
        let router = IntakeRouter(api: api)
        let outcome = await router.commit(urls: [try file("c.json")], from: .welcome)
        XCTAssertEqual(outcome.created, 3)
        XCTAssertEqual(router.inFlight, 0)
        XCTAssertEqual(router.phase, .idle, "the Welcome's Start path never opens the panel")
    }

    func testExpandWalksFoldersSkipsNoiseAndCaps() throws {
        _ = try file("export/conversations.json")
        _ = try file("export/user.json")
        _ = try file("export/images/a.png")
        _ = try file("export/.DS_Store")
        _ = try file("export/__MACOSX/conversations.json")
        let (files, capped) = IntakeRouter.expand([dir.appendingPathComponent("export")])
        XCTAssertEqual(files.map(\.lastPathComponent), ["conversations.json", "user.json"],
                       "user.json is kept: skipping it is the backend's job, reported by name")
        XCTAssertFalse(capped)
        for i in 0..<(IntakeRouter.maxFiles + 5) { _ = try file("many/f\(i).json") }
        let (many, cappedMany) = IntakeRouter.expand([dir.appendingPathComponent("many")])
        XCTAssertEqual(many.count, IntakeRouter.maxFiles)
        XCTAssertTrue(cappedMany)
    }
}
```

  `IntakeSummaryTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// Track I T5 — the sentences, pinned in en_US (every count goes through
/// `UsageFormat.count`, so another locale groups its own way).
final class IntakeSummaryTests: XCTestCase {
    private let en = Locale(identifier: "en_US")

    func testTheUpdatedClauseIsKeptAndOmittedOnlyWhenZero() {
        XCTAssertEqual(IntakeSummary.line(new: 12, updated: 3, unchanged: 40, locale: en), "12 new · 3 updated · 40 unchanged")
        XCTAssertEqual(IntakeSummary.line(new: 1_200, updated: 0, unchanged: 0, locale: en), "1,200 new · 0 unchanged")
    }

    func testTheHeadlineUsesTheVendorsNoun() {
        XCTAssertEqual(IntakeSummary.headline(IntakeOutcome(vendor: "chatgpt", created: 374, updated: 5), locale: en),
                       "379 conversations are in.")
        XCTAssertEqual(IntakeSummary.headline(IntakeOutcome(vendor: "gemini", created: 1), locale: en), "1 prompt is in.")
        XCTAssertEqual(IntakeSummary.headline(IntakeOutcome(), locale: en), Copy.intakeNothingNewHeadline)
    }

    func testTheRangeReadsAsMonths() {
        XCTAssertEqual(IntakeSummary.rangeLine(from: "2023-03-04", to: "2026-09-01", locale: en), "Mar 2023 – Sep 2026")
        XCTAssertEqual(IntakeSummary.rangeLine(from: "2026-09-01", to: "2026-09-20", locale: en), "Sep 2026")
        XCTAssertNil(IntakeSummary.rangeLine(from: nil, to: nil, locale: en))
    }

    func testThePreviewDeltaAndTheImportingLine() {
        XCTAssertEqual(IntakeSummary.previewDelta(IntakeDelta(new: 374, grown: 5, unchanged: 33), locale: en),
                       "374 new · 5 grew since last time · 33 already here")
        XCTAssertEqual(IntakeSummary.importingLine(IntakeProgress(total: 379, staged: nil), vendor: "chatgpt", locale: en),
                       "Bringing in 379 conversations…")
        XCTAssertEqual(IntakeSummary.importingLine(IntakeProgress(total: 379, staged: 180), vendor: "chatgpt", locale: en),
                       "Bringing in 180 of 379")
    }

    func testSourcesNamesTheCardTheImportWillShowUnder() {
        XCTAssertEqual(IntakeSummary.sourcesName(origin: "claude-export"), "Claude export")
        XCTAssertEqual(IntakeSummary.sourcesName(origin: "gemini-export"), "Gemini export")
        XCTAssertEqual(IntakeSummary.sourcesName(origin: nil), "Files & links")
    }
}
```

  `DockOpenQueueTests.swift`, `BundleDocumentTypesTests.swift`, `GraphDropTests.swift`:

```swift
import XCTest
import WebKit
@testable import CicadaApp

/// R-IA25 — a cold "Open With" delivers URLs before `.onAppear` attaches the router.
@MainActor
final class DockOpenQueueTests: XCTestCase {
    func testOpensWaitForTheRouterThenFlowStraightThrough() {
        let queue = DockOpenQueue()
        var seen: [[URL]] = []
        queue.receive([URL(fileURLWithPath: "/tmp/a.zip")])
        XCTAssertTrue(seen.isEmpty)
        queue.attach { seen.append($0) }
        queue.receive([URL(fileURLWithPath: "/tmp/b.json")])
        XCTAssertEqual(seen.map { $0.map(\.lastPathComponent) }, [["a.zip"], ["b.json"]])
    }
}

/// R-IA25 — Cicada is offered in Open With, never made the default opener.
final class BundleDocumentTypesTests: XCTestCase {
    func testTheBundleDeclaresAnAlternateViewerForExports() throws {
        let script = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().appendingPathComponent("bundle.sh")
        let text = try String(contentsOf: script, encoding: .utf8)
        XCTAssertTrue(text.contains("<key>CFBundleDocumentTypes</key>"))
        XCTAssertTrue(text.contains("<key>LSHandlerRank</key><string>Alternate</string>"))
        XCTAssertTrue(text.contains("<key>CFBundleTypeRole</key><string>Viewer</string>"))
        for uti in ["public.zip-archive", "public.json", "public.html", "public.folder"] {
            XCTAssertTrue(text.contains("<string>\(uti)</string>"), uti)
        }
        XCTAssertFalse(text.contains("<string>Owner</string>") || text.contains("<string>Default</string>"))
    }
}

/// D10 / R-IA24 — the graph canvas must not swallow a file drop meant for the router.
@MainActor
final class GraphDropTests: XCTestCase {
    func testTheGraphWebViewRegistersNoDragTypes() {
        let view = ClickableWebView(frame: .zero, configuration: WKWebViewConfiguration())
        XCTAssertTrue(view.registeredDraggedTypes.isEmpty)
    }
}
```

  Edits to existing tests: `TopBarControlsTests.testFeedIsTheOneCallSiteThatOptsBackIntoUpload`
  becomes

```swift
    /// Track I T5 (R-IA22) — the Upload button retired with `UploadOverlay`; the
    /// one intake owns `Store.intakeInFlight`. The parameters survive only because
    /// `Views/Sleep/SleepView.swift` passes them (Track Z owns that file).
    func testNoCallSiteOptsIntoTheRetiredUploadButton() throws {
        let sources = try ThemeTokenTests.swiftSources()
        XCTAssertFalse(sources.contains { $0.lastPathComponent == "UploadOverlay.swift" })
        for file in sources {
            let text = try String(contentsOf: file, encoding: .utf8)
            XCTAssertFalse(text.contains("showsUpload: true"), file.lastPathComponent)
        }
    }
```
  (its class doc's last paragraph is rewritten to say the same); `ImportFamilyTests:24` →
  `XCTAssertEqual(ImportFamily.chatExports.members, [.claudeExport, .chatgptExport, .geminiExport])`,
  `:43` → the same three for `previewMarks` (each now has a `logoName`); `AddSourceTileTests:14` →
  three lines `XCTAssertEqual(AddSourceTile.claudeExport.vendors, [.claude])` (and ChatGPT, Gemini),
  `:24`'s set lists the three; `ImportCatalogTests:19, 81, 188` replace `.chatExport` with the three
  cases (read each assertion — `:188` lists tiles with no `logoName`, so the three leave that list);
  `WalkthroughTests`' URL table gains `"gemini": "https://takeout.google.com/"` and add:

```swift
    /// Track I T5 — the intake takes the .zip, so no chat walkthrough says "unzip".
    func testChatWalkthroughsNeverAskToUnzip() {
        for vendor in [WalkthroughVendor.claude, .chatgpt, .gemini] {
            XCTAssertFalse(vendor.steps.contains { $0.lowercased().contains("unzip") }, vendor.rawValue)
        }
    }
```

  Run `swift test --filter "Intake|DockOpenQueue|BundleDocumentTypes|GraphDrop|TopBarControls|ImportFamily|AddSourceTile|ImportCatalog|Walkthrough"`
  → compile failure. Red.

- [ ] **Step 3: The preview, the outcome, the router** — `Support/IntakeRouter.swift`:

```swift
import Foundation
import Observation

/// Every way a file reaches Cicada (design §5.1). The seams part b and Track Z
/// use are here from day one: `.welcome`/`.home`/`.onboardingRow` (part b),
/// `.sleepRoom` (Track Z feeds the worm through `accept(urls:from:)`),
/// `.reminder` (part b's export reminders).
enum IntakeOrigin: Hashable {
    case welcome, home, windowDrop, dock, menuBar, sleepRoom
    case emptyState(AppTab)
    case feedPlus(ChatVendor?)
    case fileMenu
    case reminder(ChatVendor)
    case onboardingRow

    /// `.feedPlus` renders inside the `+` sheet; every other origin raises the
    /// window overlay (R-IA20).
    var host: IntakeHost {
        if case .feedPlus = self { return .feedPlus }
        return .overlay
    }
}

enum IntakeHost: Equatable { case overlay, feedPlus }

enum IntakeTarget: Hashable {
    case active
    case bank(String)
    case newBank(String)
}

struct IntakeProgress: Equatable {
    var total: Int
    var staged: Int?
}

enum IntakePhase: Equatable {
    case idle
    case reading([String])
    case preview(IntakePreview)
    case importing(IntakeProgress)
    case done(IntakeOutcome)
    case failed(String)
}

/// What one drop holds, aggregated over its files (design §5.2's preview).
struct IntakePreview: Equatable {
    static let maxTitles = 5000

    var chatFiles: [URL] = []
    var savedFiles: [URL] = []
    var vendor: String?
    var origin: String?
    var platform: String?
    var counts = IntakeCounts()
    var dateFrom: String?
    var dateTo: String?
    var delta = IntakeDelta()
    var titles: [IntakeTitle] = []
    var titlesTruncated = false
    var skipped: [IntakeIgnored] = []
    var warnings: [String] = []

    /// Import N = new + grew, plus saved items (design §5.2).
    var importCount: Int { delta.new + delta.grown + counts.items }

    /// "Into: New memory…" — nothing is in a bank that does not exist yet.
    func assumingEmptyBank() -> IntakePreview {
        var p = self
        p.delta = IntakeDelta(new: delta.new + delta.grown + delta.unchanged)
        return p
    }

    static func aggregate(_ files: [IntakeFileSniff], capped: Bool) -> IntakePhase {
        var p = IntakePreview()
        var vendors = Set<String>(), origins = Set<String>()
        var unreadable: [IntakeIgnored] = []
        for f in files {
            let name = f.url.lastPathComponent
            guard let s = f.sniff else {
                unreadable.append(IntakeIgnored(name: name, reason: f.error ?? Copy.intakeUnreadable))
                continue
            }
            p.skipped += s.ignored
            p.warnings += s.warnings
            guard s.recognized else {
                if let reason = s.reason { unreadable.append(IntakeIgnored(name: name, reason: reason)) }
                continue
            }
            if s.kind == "saved" {
                p.savedFiles.append(f.url)
                p.counts = p.counts + IntakeCounts(items: s.counts.items)
                p.platform = p.platform ?? s.platform
                continue
            }
            p.chatFiles.append(f.url)
            if let v = s.vendor { vendors.insert(v) }
            if let o = s.origin { origins.insert(o) }
            p.counts = p.counts + s.counts
            p.delta = p.delta + s.delta
            if let from = s.dateRange?.from { p.dateFrom = min(p.dateFrom ?? from, from) }
            if let to = s.dateRange?.to { p.dateTo = max(p.dateTo ?? to, to) }
            p.titles += s.titles
            p.titlesTruncated = p.titlesTruncated || s.titlesTruncated
        }
        if p.chatFiles.isEmpty && p.savedFiles.isEmpty {
            return .failed(unreadable.first?.reason
                            ?? p.skipped.first.map { Copy.intakeSkipped($0.name, $0.reason) }
                            ?? Copy.intakeNothingReadable)
        }
        p.skipped += unreadable
        p.vendor = vendors.count == 1 ? vendors.first : nil
        p.origin = origins.count == 1 ? origins.first : nil
        p.titles.sort { ($0.date ?? "") > ($1.date ?? "") }
        if p.titles.count > maxTitles {
            p.titles = Array(p.titles.prefix(maxTitles))
            p.titlesTruncated = true
        }
        if capped { p.warnings.append(Copy.intakeCapped(IntakeRouter.maxFiles)) }
        return .preview(p)
    }
}

/// What landed — the done card's data (design §5.2).
struct IntakeOutcome: Equatable {
    var vendor: String?
    var origin: String?
    var created = 0
    var updated = 0
    var unchanged = 0
    var savedCreated = 0
    var dateFrom: String?
    var dateTo: String?
    var bank: String?
    var bankIsActive = true
    var failures: [String] = []

    var total: Int { created + updated + savedCreated }
    /// G87: an import into a bank Sleep does not read says so, with a Switch.
    var inactiveBank: String? { bankIsActive ? nil : bank }

    mutating func add(created: Int, updated: Int, unchanged: Int, response r: IntakeImportResponse) {
        self.created += created
        self.updated += updated
        self.unchanged += unchanged
        bank = r.bank
        bankIsActive = bankIsActive && r.active
        vendor = vendor ?? r.vendor
        origin = origin ?? r.origin
        if let from = r.dateRange?.from { dateFrom = min(dateFrom ?? from, from) }
        if let to = r.dateRange?.to { dateTo = max(dateTo ?? to, to) }
    }
}

/// The one import seam (R-IA20) — testable with a fake.
protocol IntakeAPI: Sendable {
    func sniffIntake(fileURL: URL, bank: String?) async throws -> IntakeSniff
    func importIntake(fileURL: URL, bank: String?) async throws -> IntakeImportResponse
    func intakeJob(id: String) async throws -> IntakeJobStatus
    func uploadSaved(fileURL: URL) async throws -> UploadResponse
}

/// Track I T5 (design §5.1, spec decision 13) — every way a file arrives goes
/// through here: sniff → preview → import → a done card that never closes on
/// its own. Before it, the upload overlay and the `+` sheet each had their own
/// pipeline, their own folder walk and their own idea of the mascot flag
/// (D5, D6). It owns:
///
/// - `Store.intakeInFlight`, through a counter of REQUESTS in flight — a Bool
///   two overlapping intakes cleared under each other (F4), and a preview left
///   open is not an intake landing (R-IA20);
/// - the generation token `AddSourceSheet` introduced (G71 H1), hoisted: a late
///   sniff never lands on a newer preview;
/// - the folder walk (`expand`), app-side because the app reads user folders
///   and the backend parses bytes; skipping `user.json` and friends is the
///   backend's job, reported by name.
@MainActor
@Observable
final class IntakeRouter {
    /// `nonisolated`: read by the pure `expand` and `IntakePreview.aggregate`.
    nonisolated static let maxFiles = 512
    static let pollInterval: Duration = .seconds(1)
    nonisolated static let exportExtensions: Set<String> = ["json", "html", "htm", "zip", "csv", "txt", "xml", "rss", "atom", "opml"]

    private(set) var phase: IntakePhase = .idle
    private(set) var host: IntakeHost = .overlay
    private(set) var isOverlayPresented = false
    private(set) var target: IntakeTarget = .active
    private(set) var inFlight = 0

    @ObservationIgnored private let api: any IntakeAPI
    @ObservationIgnored private let sleep: @Sendable (Duration) async throws -> Void
    @ObservationIgnored private var store: Store?
    @ObservationIgnored private var generation = 0
    @ObservationIgnored private var task: Task<Void, Never>?
    @ObservationIgnored private var files: [URL] = []
    @ObservationIgnored private var capped = false
    /// The last sniff's preview, for the importing line's noun and the Into
    /// picker's "new memory" delta.
    private(set) var sniffedPreview: IntakePreview?

    init(api: any IntakeAPI = APIClient.shared,
         sleep: @escaping @Sendable (Duration) async throws -> Void = { try await Task.sleep(for: $0) }) {
        self.api = api
        self.sleep = sleep
    }

    /// Strong, like `BrowserWatcher.store` — the app owns both for its lifetime.
    func attach(store: Store) { self.store = store }

    var isImporting: Bool { if case .importing = phase { return true }; return false }
    var previewVendor: String? { sniffedPreview?.vendor }

    // MARK: Entry points

    /// No file yet — ⌘⇧I, the menu-bar item, a reminder: open the panel idle.
    func present(from origin: IntakeOrigin) {
        host = origin.host
        if host == .overlay { isOverlayPresented = true }
        if case .reading = phase { cancel() }
        if case .failed = phase { phase = .idle }
    }

    /// Files arrived. Public on purpose: Track Z's Sleep-room worm calls this
    /// with `.sleepRoom` (design §12 cross-track seam).
    func accept(urls: [URL], from origin: IntakeOrigin) {
        guard !isImporting else {
            store?.toast = Copy.intakeBusy
            return
        }
        host = origin.host
        if host == .overlay { isOverlayPresented = true }
        let expanded = Self.expand(urls)
        files = expanded.files
        capped = expanded.capped
        target = .active
        guard !files.isEmpty else {
            generation &+= 1
            phase = .failed(Copy.intakeNothingReadable)
            return
        }
        sniff()
    }

    /// The Into picker (G87). An existing bank re-sniffs, so the delta is that
    /// bank's; a new memory assumes everything is new.
    func retarget(_ newTarget: IntakeTarget) {
        guard case .preview = phase else { target = newTarget; return }
        target = newTarget
        switch newTarget {
        case .newBank:
            if let base = sniffedPreview { phase = .preview(base.assumingEmptyBank()) }
        case .active, .bank:
            sniff()
        }
    }

    // MARK: Sniff

    private var targetSlug: String? {
        if case .bank(let slug) = target { return slug }
        return nil
    }

    private func sniff() {
        generation &+= 1
        let gen = generation
        let files = self.files
        let bank = targetSlug
        let capped = self.capped
        phase = .reading(files.map(\.lastPathComponent))
        task?.cancel()
        task = Task { [weak self] in
            guard let self else { return }
            var results: [IntakeFileSniff] = []
            for url in files {
                guard gen == self.generation else { return }
                do {
                    let s = try await self.tracked { try await self.api.sniffIntake(fileURL: url, bank: bank) }
                    results.append(IntakeFileSniff(url: url, sniff: s))
                } catch {
                    results.append(IntakeFileSniff(url: url, error: AddSourceSheet.friendlyError(error)))
                }
            }
            guard gen == self.generation else { return }
            let next = IntakePreview.aggregate(results, capped: capped)
            if case .preview(let p) = next { self.sniffedPreview = p }
            self.phase = next
        }
    }

    // MARK: Import

    /// Import what the preview showed. A second tap while importing is a no-op
    /// (the M4 double-tap guard). `createBank` is the Into picker's "New memory…"
    /// (`BanksViewModel.create`), injected so the router needs no view model.
    func confirm(createBank: @escaping (String) async -> String?) {
        guard case .preview(let preview) = phase else { return }
        generation &+= 1
        let gen = generation
        let target = self.target
        phase = .importing(IntakeProgress(total: preview.importCount, staged: nil))
        task = Task { [weak self] in
            guard let self else { return }
            var outcome = IntakeOutcome(vendor: preview.vendor, origin: preview.origin)
            var bank: String?
            switch target {
            case .active: bank = nil
            case .bank(let slug): bank = slug
            case .newBank(let name):
                guard let slug = await createBank(name) else {
                    self.phase = .failed(Copy.intakeCouldNotCreate(name))
                    return
                }
                bank = slug
            }
            for url in preview.chatFiles {
                do {
                    let r = try await self.tracked { try await self.api.importIntake(fileURL: url, bank: bank) }
                    if let job = r.job {
                        let status = try await self.follow(job, gen: gen)
                        outcome.add(created: status.created, updated: status.updated, unchanged: status.skipped, response: r)
                    } else {
                        outcome.add(created: r.episodesStaged, updated: r.episodesUpdated,
                                    unchanged: r.duplicatesSkipped, response: r)
                    }
                } catch {
                    outcome.failures.append("\(url.lastPathComponent): \(AddSourceSheet.friendlyError(error))")
                }
            }
            for url in preview.savedFiles {
                do {
                    let r = try await self.tracked { try await self.api.uploadSaved(fileURL: url) }
                    outcome.savedCreated += r.episodesCreated
                    outcome.unchanged += r.duplicatesSkipped
                } catch {
                    outcome.failures.append("\(url.lastPathComponent): \(AddSourceSheet.friendlyError(error))")
                }
            }
            await self.store?.refresh([.channels, .status, .sources, .sourcesOverview, .graph, .banks])
            guard gen == self.generation else { return }
            if outcome.total == 0, outcome.unchanged == 0, let first = outcome.failures.first {
                self.phase = .failed(first)
            } else {
                self.phase = .done(outcome)
            }
        }
    }

    /// Polls a background job until it reports done — whether or not the panel
    /// is visible (R-IA20). The count shown is only ever one the job reported.
    private func follow(_ job: IntakeJobRef, gen: Int) async throws -> IntakeJobStatus {
        var status = IntakeJobStatus(id: job.id, total: job.total)
        while !status.done {
            try await sleep(Self.pollInterval)
            status = try await tracked { try await api.intakeJob(id: job.id) }
            if gen == generation, isImporting {
                phase = .importing(IntakeProgress(total: status.total, staged: status.staged))
            }
        }
        if let error = status.error { throw IntakeRouterError.job(error) }
        return status
    }

    /// Part b's Welcome Start path: import dropped files without opening the
    /// panel; the counter still owns the flag.
    func commit(urls: [URL], from origin: IntakeOrigin) async -> IntakeOutcome {
        var outcome = IntakeOutcome()
        for url in Self.expand(urls).files {
            do {
                let r = try await tracked { try await api.importIntake(fileURL: url, bank: nil) }
                if let job = r.job {
                    let status = try await follow(job, gen: -1)
                    outcome.add(created: status.created, updated: status.updated, unchanged: status.skipped, response: r)
                } else {
                    outcome.add(created: r.episodesStaged, updated: r.episodesUpdated, unchanged: r.duplicatesSkipped, response: r)
                }
            } catch {
                outcome.failures.append("\(url.lastPathComponent): \(AddSourceSheet.friendlyError(error))")
            }
        }
        await store?.refresh([.channels, .status, .sources, .sourcesOverview, .graph, .banks])
        return outcome
    }

    // MARK: Leaving

    /// Esc / Cancel: stops a sniff in flight (the generation drops its answer).
    /// Nothing can be un-imported, so an import in flight is never cancelled.
    func cancel() {
        guard !isImporting else { return }
        generation &+= 1
        task?.cancel()
        phase = .idle
        sniffedPreview = nil
    }

    /// Close the overlay. An import keeps running and reopens where it was.
    func dismiss() {
        if !isImporting, case .done = phase { phase = .idle }
        if !isImporting { cancel() }
        isOverlayPresented = false
    }

    /// The done card's Done — the ONLY way it closes (design §5.2).
    func finish() {
        phase = .idle
        sniffedPreview = nil
        isOverlayPresented = false
    }

    // MARK: Plumbing

    private func tracked<T>(_ work: () async throws -> T) async rethrows -> T {
        inFlight += 1
        store?.intakeInFlight = true
        defer {
            inFlight -= 1
            store?.intakeInFlight = inFlight > 0
        }
        return try await work()
    }

    /// Folders walked, hidden files and `__MACOSX` skipped, export-shaped
    /// extensions kept, capped at `maxFiles` with a stated warning.
    nonisolated static func expand(_ urls: [URL], fileManager fm: FileManager = .default) -> (files: [URL], capped: Bool) {
        var out: [URL] = []
        func consider(_ url: URL) {
            guard !url.lastPathComponent.hasPrefix("."), !url.pathComponents.contains("__MACOSX") else { return }
            if exportExtensions.contains(url.pathExtension.lowercased()) { out.append(url) }
        }
        for url in urls {
            var isDir: ObjCBool = false
            if fm.fileExists(atPath: url.path, isDirectory: &isDir), isDir.boolValue {
                let walker = fm.enumerator(at: url, includingPropertiesForKeys: nil,
                                           options: [.skipsHiddenFiles, .skipsPackageDescendants])
                while let next = walker?.nextObject() as? URL, out.count <= maxFiles { consider(next) }
            } else {
                consider(url)
            }
            if out.count > maxFiles { break }
        }
        out.sort { $0.path < $1.path }
        return (Array(out.prefix(maxFiles)), out.count > maxFiles)
    }
}

enum IntakeRouterError: Error, LocalizedError {
    case job(String)
    var errorDescription: String? { if case .job(let why) = self { return why }; return nil }
}
```
  Note `dismiss()` during `.preview`/`.failed` resets to idle through `cancel()`; during `.done` it
  resets (the person closed it themselves); during `.importing` it only hides.

- [ ] **Step 4: `APIClient` conformance** — append to `Services/APIClient.swift` (same file, so
  the private `uploadMultipart` and `get` are in reach):

```swift
// MARK: - One intake (Track I T5)

extension APIClient: IntakeAPI {
    private static func bankQuery(_ bank: String?) -> String {
        guard let bank else { return "" }
        return "?bank=" + (bank.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? bank)
    }

    /// `POST /intake/sniff` — stages nothing (G71 §4.3); safe on every drop.
    func sniffIntake(fileURL: URL, bank: String?) async throws -> IntakeSniff {
        try await uploadMultipart(path: "/intake/sniff" + Self.bankQuery(bank), fileURL: fileURL)
    }

    /// `POST /intake/import` — 200 with counts, or 202 with `job` (Track I T2b).
    func importIntake(fileURL: URL, bank: String?) async throws -> IntakeImportResponse {
        try await uploadMultipart(path: "/intake/import" + Self.bankQuery(bank), fileURL: fileURL)
    }

    func intakeJob(id: String) async throws -> IntakeJobStatus { try await get("/intake/jobs/\(id)") }

    /// A `kind: saved` file commits through the path that previewed it (R-IA32).
    func uploadSaved(fileURL: URL) async throws -> UploadResponse { try await uploadSource(fileURL: fileURL) }
}
```

- [ ] **Step 5: `Support/IntakeSummary.swift`:**

```swift
import Foundation

/// Track I T5 — every sentence the intake prints, pure and locale-aware. The
/// `+` sheet used to say "Imported N, skipped M" and drop G20's updated threads
/// on the floor (R7 defect 4); the `updated` clause is kept here and omitted only
/// when it is zero.
enum IntakeSummary {
    static func line(new: Int, updated: Int, unchanged: Int, locale: Locale = .autoupdatingCurrent) -> String {
        var parts = ["\(UsageFormat.count(new, locale: locale)) new"]
        if updated > 0 { parts.append("\(UsageFormat.count(updated, locale: locale)) updated") }
        parts.append("\(UsageFormat.count(unchanged, locale: locale)) unchanged")
        return parts.joined(separator: " · ")
    }

    /// A Gemini entry is one prompt and its reply (R-IA14); everything else is a conversation.
    static func noun(vendor: String?, count: Int) -> String {
        let base = vendor == "gemini" ? "prompt" : "conversation"
        return count == 1 ? base : base + "s"
    }

    static func headline(_ o: IntakeOutcome, locale: Locale = .autoupdatingCurrent) -> String {
        guard o.total > 0 else { return Copy.intakeNothingNewHeadline }
        var parts: [String] = []
        let chats = o.created + o.updated
        if chats > 0 { parts.append("\(UsageFormat.count(chats, locale: locale)) \(noun(vendor: o.vendor, count: chats))") }
        if o.savedCreated > 0 {
            parts.append("\(UsageFormat.count(o.savedCreated, locale: locale)) saved \(o.savedCreated == 1 ? "item" : "items")")
        }
        return parts.joined(separator: " and ") + (o.total == 1 ? " is in." : " are in.")
    }

    private static func month(_ day: String, locale: Locale) -> String? {
        let parse = DateFormatter()
        parse.locale = Locale(identifier: "en_US_POSIX")
        parse.timeZone = TimeZone(identifier: "UTC")
        parse.dateFormat = "yyyy-MM-dd"
        guard let date = parse.date(from: String(day.prefix(10))) else { return nil }
        let show = DateFormatter()
        show.locale = locale
        show.timeZone = TimeZone(identifier: "UTC")
        show.setLocalizedDateFormatFromTemplate("MMMyyyy")
        return show.string(from: date)
    }

    static func rangeLine(from: String?, to: String?, locale: Locale = .autoupdatingCurrent) -> String? {
        let a = from.flatMap { month($0, locale: locale) }
        let b = to.flatMap { month($0, locale: locale) }
        switch (a, b) {
        case let (a?, b?): return a == b ? a : "\(a) – \(b)"
        case let (a?, nil): return a
        case let (nil, b?): return b
        default: return nil
        }
    }

    static func previewDelta(_ d: IntakeDelta, locale: Locale = .autoupdatingCurrent) -> String {
        "\(UsageFormat.count(d.new, locale: locale)) new · \(UsageFormat.count(d.grown, locale: locale)) grew since last time · "
            + "\(UsageFormat.count(d.unchanged, locale: locale)) already here"
    }

    /// Never interpolated: the "of" form appears only once the job reported (design §5.2).
    static func importingLine(_ p: IntakeProgress, vendor: String?, locale: Locale = .autoupdatingCurrent) -> String {
        if let staged = p.staged {
            return "Bringing in \(UsageFormat.count(staged, locale: locale)) of \(UsageFormat.count(p.total, locale: locale))"
        }
        return "Bringing in \(UsageFormat.count(p.total, locale: locale)) \(noun(vendor: vendor, count: p.total))…"
    }

    static func previewTitle(_ p: IntakePreview) -> String {
        if p.chatFiles.isEmpty { return "Saved links" }
        switch p.vendor {
        case "claude": return "Claude history"
        case "chatgpt": return "ChatGPT history"
        case "gemini": return "Gemini activity"
        default: return "Chat history"
        }
    }

    static func countsLine(_ p: IntakePreview, locale: Locale = .autoupdatingCurrent) -> String {
        var parts: [String] = []
        let chats = p.counts.conversations + p.counts.prompts
        if chats > 0 { parts.append("\(UsageFormat.count(chats, locale: locale)) \(noun(vendor: p.vendor, count: chats))") }
        if p.counts.memories + p.counts.projects > 0 {
            parts.append("\(UsageFormat.count(p.counts.memories + p.counts.projects, locale: locale)) notes Claude kept")
        }
        if p.counts.items > 0 { parts.append("\(UsageFormat.count(p.counts.items, locale: locale)) saved items") }
        if let range = rangeLine(from: p.dateFrom, to: p.dateTo, locale: locale) { parts.append(range) }
        return parts.joined(separator: " · ")
    }

    static func doneDetail(_ o: IntakeOutcome, locale: Locale = .autoupdatingCurrent) -> String? {
        let parts = [rangeLine(from: o.dateFrom, to: o.dateTo, locale: locale),
                     o.updated > 0 ? "\(UsageFormat.count(o.updated, locale: locale)) grew" : nil,
                     o.unchanged > 0 ? "\(UsageFormat.count(o.unchanged, locale: locale)) unchanged" : nil].compactMap { $0 }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    static func filterCount(shown: Int, total: Int, locale: Locale = .autoupdatingCurrent) -> String {
        "\(UsageFormat.count(shown, locale: locale)) of \(UsageFormat.count(total, locale: locale))"
    }

    /// The Sources card these will show under — the Sources page's own name for
    /// it (`SourceDisplayName`), so the two cannot disagree.
    static func sourcesName(origin: String?) -> String {
        let channel = ChatVendor.allCases.first { $0.origin == origin }?.channelId ?? "files"
        return SourceDisplayName.of(SourceOverview(id: channel, label: "", kind: .import))
    }
}
```

- [ ] **Step 6: The views** — `Views/Intake/IntakeOverlay.swift` (the overlay, the drop veil, the
  shared drop loader and the vendor mark):

```swift
import AppKit
import SwiftUI

/// Resolves the file URLs a drop carries, then hands them over on the main actor.
/// One loader for every drop target (the window, an empty state, the panel).
enum IntakeDrop {
    static func load(_ providers: [NSItemProvider], _ completion: @escaping @MainActor ([URL]) -> Void) {
        let group = DispatchGroup()
        let lock = NSLock()
        var urls: [URL] = []
        for provider in providers where provider.canLoadObject(ofClass: URL.self) {
            group.enter()
            _ = provider.loadObject(ofClass: URL.self) { url, _ in
                if let url { lock.lock(); urls.append(url); lock.unlock() }
                group.leave()
            }
        }
        group.notify(queue: .main) { MainActor.assumeIsolated { completion(urls) } }
    }
}

/// A chat vendor's real mark (Track L precedence through `OriginIconography`),
/// never recoloured; decorative, so hidden from VoiceOver (the text names it).
struct VendorMark: View {
    let origin: String?
    var size: CGFloat

    init(vendor: ChatVendor, size: CGFloat) { self.origin = vendor.origin; self.size = size }
    init(origin: String?, size: CGFloat) { self.origin = origin; self.size = size }

    var body: some View {
        LogoImage.platformTile(name: origin.flatMap(OriginIconography.logoName(for:)) ?? "",
                               size: size, systemFallback: "bubble.left.and.bubble.right")
            .accessibilityHidden(true)
    }
}

/// What sits over the whole window: the drop veil while a file is dragged over
/// it (I1), and the intake overlay while the router shows it (design §5.1). A
/// ZStack layer, not a `.sheet`, so it can sit above any page and share the veil.
struct IntakeLayer: View {
    let dropTargeted: Bool
    @Environment(IntakeRouter.self) private var intake
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        ZStack {
            if intake.isOverlayPresented { IntakeOverlay().transition(.opacity) }
            if dropTargeted { IntakeDropVeil().transition(.opacity) }
        }
        .animation(CicadaMotion.dropVeil(reduceMotion: reduceMotion), value: dropTargeted)
        .animation(CicadaMotion.panel(reduceMotion: reduceMotion), value: intake.isOverlayPresented)
    }
}

struct IntakeDropVeil: View {
    var body: some View {
        ZStack {
            CicadaTheme.scrim.ignoresSafeArea()
            RoundedRectangle(cornerRadius: CicadaTheme.radiusLarge, style: .continuous)
                .strokeBorder(CicadaTheme.accent, style: StrokeStyle(lineWidth: 2, dash: [8, 6]))
                .padding(CicadaTheme.scaled(12))
            VStack(spacing: CicadaTheme.spacingSM) {
                HStack(spacing: CicadaTheme.spacingSM) {
                    ForEach(ChatVendor.allCases) { VendorMark(vendor: $0, size: CicadaTheme.scaled(28)) }
                }
                Text(Copy.intakeVeil).font(CicadaTheme.headingFont).foregroundStyle(CicadaTheme.textPrimary)
            }
            .padding(CicadaTheme.spacingLG)
            .background(CicadaTheme.surface, in: RoundedRectangle(cornerRadius: CicadaTheme.cornerRadius, style: .continuous))
        }
        .allowsHitTesting(false)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(Copy.intakeVeil)
    }
}

struct IntakeOverlay: View {
    @Environment(IntakeRouter.self) private var intake

    var body: some View {
        ZStack {
            CicadaTheme.scrim
                .ignoresSafeArea()
                .onTapGesture { intake.dismiss() }
                .accessibilityHidden(true)
            ScrollView {
                IntakePanel(origin: .windowDrop)
                    .padding(CicadaTheme.spacingXL)
            }
            .scrollBounceBehavior(.basedOnSize)
            .frame(maxWidth: CicadaTheme.scaled(600), maxHeight: CicadaTheme.scaled(640))
            .fixedSize(horizontal: false, vertical: true)
            .background(CicadaTheme.surface, in: RoundedRectangle(cornerRadius: CicadaTheme.radiusLarge, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: CicadaTheme.radiusLarge, style: .continuous)
                .stroke(CicadaTheme.border, lineWidth: 1))
            .padding(CicadaTheme.spacingXL)
        }
        .onKeyPress(.escape) { intake.dismiss(); return .handled }
    }
}
```

  `Views/Intake/IntakePanel.swift`:

```swift
import AppKit
import SwiftUI
import UniformTypeIdentifiers

/// Track I T5 (design §5.2) — the one intake panel. One component, many hosts:
/// the window overlay, each `+` chat tile, the `+` root's drop zone (and, in part
/// b, the Welcome and Home). It renders the router's `phase` and owns no import
/// logic, so a Dock drop and a `+` tile cannot behave differently.
struct IntakePanel: View {
    /// nil: every vendor (the overlay, the `+` root); set: one tile's vendor.
    var vendor: ChatVendor? = nil
    /// Where this panel's own drops and file picks say they came from.
    var origin: IntakeOrigin
    /// The `+` root: the drop zone alone, no "how to get it".
    var compact = false

    @Environment(IntakeRouter.self) private var intake
    @Environment(BanksViewModel.self) private var banksVM
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var dropTargeted = false
    @State private var filter = ""
    @State private var newMemoryName = ""
    @State private var creatingNew = false

    private var vendors: [ChatVendor] { vendor.map { [$0] } ?? ChatVendor.allCases }
    /// A panel shows the router's phase only when it is the host that phase belongs to.
    private var phase: IntakePhase { intake.host == origin.host ? intake.phase : .idle }

    var body: some View {
        Group {
            switch phase {
            case .idle: idle
            case .reading(let names): reading(names)
            case .preview(let preview): self.preview(preview)
            case .importing(let progress): importing(progress)
            case .done(let outcome): IntakeDoneCard(outcome: outcome) { intake.finish() }
            case .failed(let reason): failed(reason)
            }
        }
        .animation(CicadaMotion.morph(reduceMotion: reduceMotion), value: phase)
    }

    // MARK: Idle

    private var idle: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            dropZone
            if !compact {
                Text(Copy.intakeNoExportYet).font(CicadaTheme.headingFont).foregroundStyle(CicadaTheme.textPrimary)
                ForEach(vendors) { VendorExportRow(vendor: $0, startsOpen: vendor != nil) }
            }
        }
    }

    private var dropZone: some View {
        VStack(spacing: CicadaTheme.spacingSM) {
            HStack(spacing: CicadaTheme.spacingSM) {
                ForEach(vendors) { VendorMark(vendor: $0, size: CicadaTheme.scaled(28)) }
            }
            Text(Copy.intakeDropTitle).font(CicadaTheme.headingFont).foregroundStyle(CicadaTheme.textPrimary)
            Text(Copy.intakeDropSubtitle).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                .multilineTextAlignment(.center)
            Button(Copy.intakeChooseFile) { chooseFile() }
                .buttonStyle(.bordered)
                .keyboardShortcut(.defaultAction)
        }
        .frame(maxWidth: .infinity)
        .padding(CicadaTheme.spacingLG)
        .background(dropTargeted ? CicadaTheme.meadowWash.opacity(0.4) : CicadaTheme.surface,
                    in: RoundedRectangle(cornerRadius: CicadaTheme.cornerRadius, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadius, style: .continuous)
            .strokeBorder(dropTargeted ? CicadaTheme.meadow : CicadaTheme.border,
                          style: StrokeStyle(lineWidth: dropTargeted ? 2 : 1, dash: [6, 4])))
        .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: dropTargeted)
        .onDrop(of: [.fileURL], isTargeted: $dropTargeted) { providers in
            IntakeDrop.load(providers) { intake.accept(urls: $0, from: origin) }
            return true
        }
    }

    private func chooseFile() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.zip, .json, .html, .folder, .commaSeparatedText, .plainText, .xml]
        panel.allowsMultipleSelection = true
        panel.canChooseDirectories = true
        panel.message = Copy.intakeDropTitle
        guard panel.runModal() == .OK else { return }
        intake.accept(urls: panel.urls, from: origin)
    }

    // MARK: Reading / importing / failed

    private func reading(_ names: [String]) -> some View {
        VStack(spacing: CicadaTheme.spacingMD) {
            BookwormView(state: .reading, pointSize: 48)
            Text(Copy.intakeReading(names)).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary)
            Button(Copy.intakeCancel) { intake.cancel() }.buttonStyle(.bordered).keyboardShortcut(.cancelAction)
        }
        .frame(maxWidth: .infinity)
    }

    private func importing(_ progress: IntakeProgress) -> some View {
        VStack(spacing: CicadaTheme.spacingMD) {
            BookwormView(state: .reading, pointSize: 48)
            Text(IntakeSummary.importingLine(progress, vendor: intake.previewVendor))
                .font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textPrimary)
            if let staged = progress.staged {
                ProgressView(value: Double(staged), total: Double(max(progress.total, 1)))
                    .frame(maxWidth: CicadaTheme.scaled(280))
            }
        }
        .frame(maxWidth: .infinity)
    }

    private func failed(_ reason: String) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            Text(reason).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.danger)
                .fixedSize(horizontal: false, vertical: true)
            HStack {
                Button(Copy.intakeChooseAnother) { chooseFile() }.buttonStyle(.bordered)
                Spacer()
                Button(Copy.intakeCancel) { intake.cancel() }.buttonStyle(.cicadaPlain)
                    .foregroundStyle(CicadaTheme.textSecondary)
            }
        }
        .onAppear { AccessibilityNotification.Announcement(reason).post() }
    }

    // MARK: Preview

    private func preview(_ p: IntakePreview) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            HStack(spacing: CicadaTheme.spacingSM) {
                VendorMark(origin: p.origin, size: CicadaTheme.scaled(32)).markHover()
                VStack(alignment: .leading, spacing: 2) {
                    Text(IntakeSummary.previewTitle(p)).font(CicadaTheme.titleFont)
                        .foregroundStyle(CicadaTheme.textPrimary).accessibilityAddTraits(.isHeader)
                    Text(IntakeSummary.countsLine(p)).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                }
            }
            if !p.chatFiles.isEmpty {
                Text(IntakeSummary.previewDelta(p.delta)).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textPrimary)
            }
            if !p.titles.isEmpty { titleList(p) }
            ForEach(Array(p.skipped.enumerated()), id: \.offset) { _, s in
                Text(Copy.intakeSkipped(s.name, s.reason)).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
            }
            ForEach(p.warnings, id: \.self) {
                Text($0).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
            }
            if !p.chatFiles.isEmpty { intoPicker }
            if p.importCount == 0 {
                Text(Copy.intakeNothingNewLine).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
            }
            HStack {
                Spacer()
                Button(Copy.intakeCancel) { intake.cancel() }.buttonStyle(.cicadaPlain)
                    .foregroundStyle(CicadaTheme.textSecondary).keyboardShortcut(.cancelAction)
                MeadowPill(title: p.importCount == 0 ? Copy.intakeNothingNew : Copy.intakeImportButton(p.importCount)) {
                    intake.confirm(createBank: { name in await banksVM.create(name: name) })
                }
                .disabled(p.importCount == 0 || (creatingNew && newMemoryName.trimmingCharacters(in: .whitespaces).isEmpty))
            }
        }
    }

    private func titleList(_ p: IntakePreview) -> some View {
        let shown = filter.isEmpty ? p.titles : p.titles.filter { $0.title.localizedCaseInsensitiveContains(filter) }
        return VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            HStack {
                TextField(Copy.intakeFilterPlaceholder, text: $filter)
                    .textFieldStyle(.roundedBorder)
                    .accessibilityLabel(Copy.intakeFilterLabel)
                Text(IntakeSummary.filterCount(shown: shown.count, total: p.titles.count))
                    .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
            }
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 2) {
                    ForEach(Array(shown.enumerated()), id: \.offset) { _, t in
                        HStack {
                            Text(t.title).font(CicadaTheme.bodyFont).lineLimit(1)
                            Spacer()
                            if let date = t.date { Text(date).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary) }
                        }
                    }
                }
            }
            .frame(maxHeight: CicadaTheme.scaled(200))
            if p.titlesTruncated {
                Text(Copy.intakeTitlesCapped(IntakePreview.maxTitles)).font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
        }
    }

    /// Into (G87): this memory, another, or a new one — the upload overlay's
    /// project mode, absorbed.
    private var intoPicker: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            Text(Copy.intakeInto).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
            Picker(Copy.intakeInto, selection: Binding(
                get: { creatingNew ? "__new__" : (targetSlug ?? banksVM.activeName ?? "") },
                set: { value in
                    if value == "__new__" {
                        creatingNew = true
                        intake.retarget(.newBank(newMemoryName))
                    } else {
                        creatingNew = false
                        intake.retarget(value == banksVM.activeName ? .active : .bank(value))
                    }
                })) {
                ForEach(banksVM.banks) { bank in
                    Text(bank.name == banksVM.activeName ? "\(bank.name) \(Copy.intakeActiveSuffix)" : bank.name).tag(bank.name)
                }
                Divider()
                Text(Copy.intakeNewMemory).tag("__new__")
            }
            .labelsHidden()
            .pickerStyle(.menu)
            if creatingNew {
                TextField(Copy.intakeNewMemoryPlaceholder, text: $newMemoryName)
                    .textFieldStyle(.roundedBorder)
                    .onChange(of: newMemoryName) { _, name in intake.retarget(.newBank(name)) }
            }
        }
        .task { await banksVM.load() }
    }

    private var targetSlug: String? {
        if case .bank(let slug) = intake.target { return slug }
        return nil
    }
}

/// "Don't have one yet?" — one vendor's mark, what you get, the export page,
/// and the steps (none of them "unzip" — the intake takes the .zip).
private struct VendorExportRow: View {
    let vendor: ChatVendor
    let startsOpen: Bool
    @State private var hovering = false
    @State private var showSteps = false

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            HStack(spacing: CicadaTheme.spacingSM) {
                VendorMark(vendor: vendor, size: CicadaTheme.scaled(22)).markHover(hovering: hovering)
                VStack(alignment: .leading, spacing: 2) {
                    Text(vendor.title).font(CicadaTheme.font(size: 13, weight: .semibold)).foregroundStyle(CicadaTheme.textPrimary)
                    Text(vendor.walkthrough.summary).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                }
                Spacer()
                Button { NSWorkspace.shared.open(vendor.walkthrough.exportURL) } label: {
                    Label(Copy.intakeOpenExportPage, systemImage: "arrow.up.right.square")
                }
                .buttonStyle(.bordered)
                .accessibilityLabel("\(Copy.intakeOpenExportPage), \(vendor.title)")
            }
            DisclosureGroup(isExpanded: $showSteps) {
                VStack(alignment: .leading, spacing: 2) {
                    ForEach(Array(vendor.walkthrough.steps.enumerated()), id: \.offset) { i, step in
                        Text("\(i + 1). \(step)").font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                    }
                }
            } label: {
                Text(Copy.intakeHowToGet).font(CicadaTheme.captionFont)
            }
        }
        .onHover { hovering = $0 }
        .onAppear { showSteps = startsOpen }
    }
}
```

  `Views/Intake/IntakeDoneCard.swift`:

```swift
import SwiftUI

/// Track I T5 (design §5.2) — "what happens next". It never closes on its own:
/// the upload overlay's 1.5 s auto-dismiss took the one sentence that says when
/// these will be read away before anyone could read it (D6). The when-line is
/// `ScheduleHonesty.afterImportLine` (A/B/C — ruling 4 shown, never promised
/// away); Read now is G125 R10's first narrow amendment (R-IA31): a user
/// trigger, shown only when an engine can run it (`EngineReadiness`, else a link
/// to choose one — R-IA23) and only when the import landed in the bank a read
/// consolidates.
struct IntakeDoneCard: View {
    let outcome: IntakeOutcome
    let onDone: () -> Void

    @Environment(SleepViewModel.self) private var sleepVM
    @Environment(SleepEngineViewModel.self) private var engineVM
    @Environment(Store.self) private var store
    @Environment(AppRouter.self) private var router
    @Environment(BanksViewModel.self) private var banksVM
    @Environment(GraphViewModel.self) private var graphVM
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var readingNow = false
    @State private var switchedTo: String?
    @State private var switching = false
    @State private var check = 0

    private var inputs: HonestyInputs {
        HonestyInputs.from(schedule: sleepVM.schedule, response: engineVM.response,
                           connections: store.connections.value ?? [])
    }

    private var readiness: EngineReadiness {
        EngineReadiness.resolve(candidates: engineVM.response?.candidates ?? [],
                                connections: store.connections.value ?? [],
                                preview: engineVM.response?.preview)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            HStack(spacing: CicadaTheme.spacingSM) {
                Image(systemName: "checkmark.circle.fill")
                    .font(CicadaTheme.font(size: 22))
                    .foregroundStyle(CicadaTheme.success)
                    .symbolEffect(.bounce, value: check)
                    .symbolEffectsRemoved(reduceMotion)
                Text(IntakeSummary.headline(outcome)).font(CicadaTheme.titleFont)
                    .foregroundStyle(CicadaTheme.textPrimary).accessibilityAddTraits(.isHeader)
            }
            if let detail = IntakeSummary.doneDetail(outcome) {
                Text(detail).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
            }
            ForEach(outcome.failures, id: \.self) {
                Text($0).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.danger)
            }
            if let bank = outcome.inactiveBank, switchedTo == nil {
                Text(Copy.intakeInactiveBank(bank)).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.warning)
                Button(Copy.intakeSwitchTo(bank)) { switchTo(bank) }.buttonStyle(.bordered).disabled(switching)
            } else if outcome.total > 0 {
                Text(ScheduleHonesty.afterImportLine(inputs)).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)
                readRow
            }
            HStack {
                Button(Copy.whatNextShowsIn(IntakeSummary.sourcesName(origin: outcome.origin))) {
                    router.pendingTab = .sources
                    onDone()
                }
                .buttonStyle(.link)
                Spacer()
                Button(Copy.intakeDone, action: onDone).keyboardShortcut(.defaultAction)
            }
        }
        .task {
            check &+= 1
            AccessibilityNotification.Announcement(IntakeSummary.headline(outcome)).post()
            await engineVM.load()
            await sleepVM.load()
        }
    }

    @ViewBuilder private var readRow: some View {
        if readingNow {
            Text(Copy.intakeReadingNow).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
        } else if case .ready = readiness, let preview = engineVM.response?.preview {
            HStack(spacing: CicadaTheme.spacingSM) {
                MeadowPill(title: Copy.intakeReadNow) {
                    readingNow = true
                    Task { await sleepVM.triggerManually() }
                }
                Text(Copy.engineLabel(preview.manual.engine)).font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
            }
        } else {
            SettingsSectionLink(section: .sleep, label: Copy.intakeChooseWhoReads)
        }
    }

    /// G87's one-click remedy, moved from the upload overlay unchanged.
    private func switchTo(_ bank: String) {
        switching = true
        Task {
            if await banksVM.activate(bank) {
                await graphVM.loadGraph()
                switchedTo = bank
            }
            switching = false
        }
    }
}
```

- [ ] **Step 7: Entry points.**
  - **The app root** — `CicadaApp.swift`: add `@State private var intakeRouter = IntakeRouter()` beside
    `browserWatcher` (`:47`) and
    `@NSApplicationDelegateAdaptor(CicadaAppDelegate.self) private var appDelegate`; the
    `WindowGroup` content gains `.environment(intakeRouter)` and
    `.handlesExternalEvents(preferring: Set(["*"]), allowing: Set(["*"]))` (R-IA24); in `.onAppear`
    after `browserWatcher.start(store: store)`:

```swift
                    // Track I T5 — the one intake owns `store.intakeInFlight`
                    // through its request counter, and the Dock's opens wait in
                    // `DockOpenQueue` until this line attaches it (R-IA25).
                    intakeRouter.attach(store: store)
                    appDelegate.opens.attach { [intakeRouter] urls in
                        NSApplication.shared.activate(ignoringOtherApps: true)
                        intakeRouter.accept(urls: urls, from: .dock)
                    }
```
    `menuBarManager.setup(…)` gains `onImportFile: { [intakeRouter] in NSApplication.shared.activate(ignoringOtherApps: true);
    NSApplication.shared.windows.first(where: { $0.canBecomeKey })?.makeKeyAndOrderFront(nil);
    intakeRouter.present(from: .menuBar) }`. The `.commands` block (`:212-221`) gains:

```swift
            // Track I T5 — File → Import… (⌘⇧I): the keyboard and VoiceOver twin
            // of every drop (design §5.1).
            CommandGroup(after: .newItem) {
                Button(Copy.intakeFileMenuItem) { intakeRouter.present(from: .fileMenu) }
                    .keyboardShortcut("i", modifiers: [.command, .shift])
            }
```
  - **`Support/DockOpenQueue.swift`:**

```swift
import AppKit

/// R-IA25 — URLs from the Dock ("Open With", a drop on the icon) arrive through
/// the app delegate, and on a cold launch they arrive BEFORE `ContentView`'s
/// `.onAppear` has attached the router. They wait here, then flow straight through.
@MainActor
final class DockOpenQueue {
    private var pending: [URL] = []
    private var handler: (([URL]) -> Void)?

    func receive(_ urls: [URL]) {
        guard !urls.isEmpty else { return }
        if let handler { handler(urls) } else { pending += urls }
    }

    func attach(_ handler: @escaping ([URL]) -> Void) {
        self.handler = handler
        guard !pending.isEmpty else { return }
        let urls = pending
        pending = []
        handler(urls)
    }
}

/// The one AppKit hook SwiftUI's `App` lacks for a Dock open (F10).
@MainActor
final class CicadaAppDelegate: NSObject, NSApplicationDelegate {
    let opens = DockOpenQueue()

    func application(_ application: NSApplication, open urls: [URL]) {
        opens.receive(urls)
    }
}
```
  - **`bundle.sh`** — inside the Info.plist heredoc, after `NSPrincipalClass`:

```xml
  <key>CFBundleDocumentTypes</key>
  <array>
    <dict>
      <key>CFBundleTypeName</key><string>Chat export</string>
      <key>CFBundleTypeRole</key><string>Viewer</string>
      <key>LSHandlerRank</key><string>Alternate</string>
      <key>LSItemContentTypes</key>
      <array>
        <string>public.zip-archive</string>
        <string>public.json</string>
        <string>public.html</string>
        <string>public.folder</string>
      </array>
    </dict>
  </array>
```
    with a comment above the heredoc: `# Track I T5 (R-IA25): offered in Open With and as a Dock drop
    target, never the default opener (LSHandlerRank Alternate).`
  - **The window** — `ContentView.swift`: add `@Environment(IntakeRouter.self) private var intake`
    and `@State private var dropTargeted = false`; on the `NavigationSplitView` chain (after
    `.navigationSplitViewStyle(.prominentDetail)`):

```swift
        // Track I T5 (R-IA24) — drop anywhere: one window-level target, the veil
        // while a file hovers, the overlay while the router shows it.
        .overlay { IntakeLayer(dropTargeted: dropTargeted) }
        .onDrop(of: [.fileURL], isTargeted: $dropTargeted) { providers in
            IntakeDrop.load(providers) { intake.accept(urls: $0, from: .windowDrop) }
            return true
        }
```
    and the Graph empty state (`:258-263`) passes
    `onDropFiles: { intake.accept(urls: $0, from: .emptyState(.graph)) }` — `GraphContainerView`
    gains the same `@Environment(IntakeRouter.self)`.
  - **The graph canvas** — `GraphView.swift:11-14`:

```swift
final class ClickableWebView: WKWebView {
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
    override var acceptsFirstResponder: Bool { true }
    /// Track I T5 (D10, R-IA24): a WKWebView registers for file drags itself and
    /// would load a dropped export INTO the canvas. Never registering lets the drop
    /// fall through to the window's one intake.
    override func registerForDraggedTypes(_ newTypes: [NSPasteboard.PasteboardType]) {}
}
```
  - **The menu bar** — `MenuBarManager.swift`: `private var onImportFile: (() -> Void)?`; `setup`
    gains the `onImportFile: @escaping () -> Void` parameter (stored); in `rebuildMenu` between the
    *Save clipboard URL* and *Open Cicada* items:

```swift
        // Track I T5 (R-IA26): the one intake from the menu bar; the status
        // button as a drag target waits on design §14 item 5.
        let importItem = NSMenuItem(title: Copy.intakeMenuBarItem, action: #selector(importFileAction), keyEquivalent: "i")
        importItem.target = self
        menu.addItem(importItem)
```
    and `@objc private func importFileAction() { onImportFile?() }` beside the other actions.
  - **Empty states** — `EmptyStateView.swift` gains `var onDropFiles: (([URL]) -> Void)? = nil`
    and `@State private var dropTargeted = false`; inside the card, after the action block:

```swift
                if onDropFiles != nil {
                    Label(Copy.emptyStateDropHint, systemImage: "tray.and.arrow.down")
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(dropTargeted ? CicadaTheme.meadow : CicadaTheme.textTertiary)
                        .padding(.top, CicadaTheme.spacingXS)
                }
```
    and on the card (after its `.overlay(…stroke…)`) `.modifier(EmptyStateDrop(onDropFiles:
    onDropFiles, targeted: $dropTargeted))` with, in the same file:

```swift
/// Track I T5 (R-IA27) — an empty page that can be filled by an export takes the
/// drop itself; one that cannot (Inbox) attaches no target, so the window's
/// handler still gets the drop.
private struct EmptyStateDrop: ViewModifier {
    let onDropFiles: (([URL]) -> Void)?
    @Binding var targeted: Bool

    @ViewBuilder
    func body(content: Content) -> some View {
        if let onDropFiles {
            content.onDrop(of: [.fileURL], isTargeted: $targeted) { providers in
                IntakeDrop.load(providers) { onDropFiles($0) }
                return true
            }
        } else {
            content
        }
    }
}
```
    Feed (`FeedView.swift:242`) and Sources (`SourceCardGrid.swift:53`) pass
    `onDropFiles: { intake.accept(urls: $0, from: .emptyState(.feed)) }` / `(.sources)` with their own
    `@Environment(IntakeRouter.self) private var intake`.
  - **`Sync/Store.swift:81-89`** — the `intakeInFlight` doc becomes: "G125 R2 / Track I T5 — true
    while the `IntakeRouter` has a sniff, an import or a job poll in flight (its request counter owns
    this flag; no view writes it). The Sleep page's mood reads it to force `.reading`… Never persisted."

- [ ] **Step 8: Retire the overlay and the Upload button (R-IA22).**
  - `git rm app/CicadaApp/Sources/CicadaApp/Views/Common/UploadOverlay.swift` (with it go
    `UploadMode`, `UploadHistoryEntry`, `UploadHistoryStore`, the literal `.spring`/`.easeInOut`
    and the `Color.black.opacity(0.4)` scrim).
  - `FeedView.swift`: delete `showUploadOverlay` (`:14`), the `if showUploadOverlay { UploadOverlay… }`
    block (`:90-93`), its `.onChange` and `.animation` (`:99-103`), and the long *Final review F1*
    comment (`:62-77`); `TopBarControls(selectedTab: $selectedTab, showUploadOverlay: .constant(false))`
    replaces the `showsUpload: true` call.
  - `TopBarControls.swift`: delete the Upload button block (`:77-93`); the two parameters stay with
    this doc in place of `:28-36`:

```swift
    /// Track I T5 (R-IA22): inert. The Upload button retired with `UploadOverlay`
    /// — every file now arrives through the one `IntakeRouter`, which owns
    /// `Store.intakeInFlight`. The parameter (and `showUploadOverlay`) survive only
    /// because `Views/Sleep/SleepView.swift` passes them and Track Z owns that
    /// file; `TopBarControlsTests` fails if any call site passes `true`.
    var showsUpload: Bool = false
```
  - `APIClient.swift`: delete `uploadFile(fileURL:)` and `importToBank(name:fileURL:)` once
    `grep -rn "uploadFile(\|importToBank(" app/CicadaApp/Sources` is empty; keep `BankImportResponse`
    (its decode test documents the shim's shape for external callers).

- [ ] **Step 9: Three chat tiles and a Gemini walkthrough (R-IA21).**
  - `WalkthroughPanel.swift`: `enum WalkthroughVendor` gains `case gemini` (appended, so raw values
    never move); `title` "Gemini"; `exportURL` `https://takeout.google.com/`; `summary` "Your
    Gemini prompts and replies, each with its date."; steps:

```swift
        case .claude: [
            "Open Settings → Privacy on claude.ai.",
            "Click “Export data” and confirm.",
            "Anthropic emails you a link to a .zip.",
            "Drop the .zip here, just as it arrived.",
        ]
        case .chatgpt: [
            "Open Settings → Data controls on chatgpt.com.",
            "Click “Export data” and confirm.",
            "OpenAI emails you a link to a .zip.",
            "Drop the .zip here, just as it arrived.",
        ]
        case .gemini: [
            "Open Google Takeout and click “Deselect all”.",
            "Tick “My Activity”, then keep only “Gemini Apps” in its list.",
            "Export once as a .zip and download it.",
            "Drop the .zip here, just as it arrived.",
        ]
```
    `Theme/Copy.swift`: `claudeStepPath` → `"Settings > Privacy > Export data > check your email >
    download the .zip"` (unchanged), and add `static let geminiStepPath = "Takeout > Deselect all >
    My Activity > Gemini Apps > Export > download the .zip"` with `case .gemini: return
    geminiStepPath` in `exportStepPath`.
  - `AddSourceSheet.swift`: the first case line becomes
    `case claudeExport, chatgptExport, geminiExport, bookmarksFile, pasteLink, rssFeed, calendar`,
    plus

```swift
    /// Track I T5 (R-IA21): the chat vendor a tile imports, nil for every other tile.
    var chatVendor: ChatVendor? {
        switch self {
        case .claudeExport: .claude
        case .chatgptExport: .chatgpt
        case .geminiExport: .gemini
        default: nil
        }
    }
```
    and in each switch: `route` → the three join `.importFile`; `title` → `chatVendor!.title`
    for the three (write `case .claudeExport, .chatgptExport, .geminiExport: chatVendor?.title ?? ""`);
    `blurb` → `chatVendor?.walkthrough.summary ?? ""`; `icon` → `"bubble.left.and.bubble.right"`;
    `channelIds` → `[chatVendor!.channelId]` (spelled out per case: `["chat-export:claude"]`, …);
    `logoName` → `chatVendor.flatMap { OriginIconography.logoName(for: $0.origin) }` for the three
    (they leave the `nil` list at `:171`); `vendors` → `[chatVendor!.walkthrough]` per case. In
    `flow(for:)` (`:583-584`):

```swift
            case .claudeExport, .chatgptExport, .geminiExport:
                // Track I T5 — the one intake, in place (R-IA20: `.feedPlus` never
                // raises the window overlay behind this sheet).
                IntakePanel(vendor: tile.chatVendor, origin: .feedPlus(tile.chatVendor))
```
    At the families level (`:309-316`), above the `LazyVGrid`, add the root drop zone:
    `IntakePanel(origin: .feedPlus(nil), compact: true)` followed by `.padding(.bottom,
    CicadaTheme.spacingMD)`. Delete `pickChatExport` (`:782-792`) and `expandToFiles` (`:909-927`).
    `runImport` (`:881-907`, still used by `pickSavedContent`) sums `episodesUpdated` too and its
    success line becomes `IntakeSummary.line(new: created, updated: updated, unchanged: skipped)`
    (+ `" (some files failed)"` as today) — R7 defect 4.
  - `ImportFamilies.swift`: `chatExports` blurb → "Claude, ChatGPT and Gemini, each chat with its
    date."; members → `[.claudeExport, .chatgptExport, .geminiExport]`; `routeLines` → Claude and
    ChatGPT `["The .zip, a folder, or conversations.json"]`, Gemini `["The Takeout .zip or
    MyActivity.html"]`.
  - `Views/Settings/IntegrationsView.swift` and anything else `grep -rn "\.chatExport\b" Sources`
    finds: point at the matching vendor tile (`AddSourceTile.forChannel` already resolves each
    channel to its own tile).

- [ ] **Step 10: Green.** `swift build`, `swift test` (0 failures; the lints —
  `MotionLiteralLintTests`, `FontLiteralLintTests`, `LiquidGlassLintTests`, `ThemeTokenTests`,
  `MeadowPlacementLintTests` — included), `node --test app/CicadaApp/Tests/graph/*.test.js`, and the
  full backend suite (untouched by this task, re-run because the app now calls new routes).

- [ ] **Step 11: Docs.** `CLAUDE.md`, Navigation paragraph — replace the three sentences from
  "**The Feed keeps its Upload button**…" to "…while an import lands." with:

  > **One intake (Track I, spec decision 13).** Every way a file arrives — a drop anywhere on the window, the Dock icon, File → Import… (⌘⇧I), the menu-bar worm's *Import a file…*, an empty state, each `+` chat tile — goes through one `IntakeRouter`: sniff (`POST /intake/sniff`, stages nothing) → preview (counts, date range, new · grew · already here, skipped files by name, *Into* a memory) → import (`POST /intake/import`; a 202 and a job counter above 10 episodes) → a *what happens next* card that never closes on its own. `UploadOverlay` and the Feed's Upload button are gone; the router owns `Store.intakeInFlight` through a counter of requests in flight. The card's *Read now* is G125 R10's first narrow amendment: a user trigger, subtitled with the manual engine like Consolidate, shown only when an engine can run and the import landed in the active bank.

  and in *Mascot states* replace "(set while the upload overlay runs)" with "(set while the intake
  router has a request in flight)". `memory-evolution.md` — append to G64:

  > **Track I T5 (2026-09-23):** the chat walkthroughs no longer say "unzip" (the intake takes the .zip), Gemini joins with a Takeout walkthrough, and each vendor has its own `+` tile with its real mark and an Open export page link. Recordings still open.

  to G87:

  > **Track I T5 (2026-09-23):** every import path now reaches the non-active-bank consequence — the intake preview's *Into* (this memory, another, or a new one) replaces the overlay's project mode, and the done card says the memory isn't active, with Switch. The discriminator and the sidebar hoist stay open.

  and to G125:

  > **Track I (2026-09-23) — R10 narrow amendment 1 of 2 (design §10):** the intake done card's *Read now* is a user trigger, subtitled with `preview.manual`'s engine like Consolidate, shown only when `EngineReadiness` says an engine can run and the import landed in the active bank. Part b adds Getting started's.

- [ ] **Step 12: Commit** — stage every file this task created, modified or deleted (list them
  with `git status --short`, never `-A`), then
  `git commit -m "feat(intake): one intake in the app — drop anywhere, Dock, ⌘⇧I, menu bar, + tiles; UploadOverlay retired (Track I T5, G64/G87)" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"`.

---

### Task 8 (T7): On this Mac — detection, and agent connect after a click

Design §4.1.3 (detection), §4.1.6 (who executes), spec decision 14 (D-1 answered yes). Its first
host is the `+` sheet's *On this Mac* strip (R-IA30); part b's Welcome reuses every piece.

**Files:**
- Create: `app/…/Models/AgentWiring.swift`, `Support/LocalInventory.swift`, `Support/AgentConnect.swift`, `Views/Intake/OnThisMacStrip.swift`
- Modify: `Services/APIClient.swift` (`fetchAgentWiring`), `Views/Capture/Sheets/AddSourceSheet.swift` (families level)
- Test: `LocalInventoryTests.swift`, `AgentConnectTests.swift`, `AgentWiringCatalogTests.swift` (new)
- Docs: `memory-evolution.md` (G117), `docs/goals/TODO.md`

**Interfaces:** `AgentWiringResponse`/`AgentWiring`/`AgentWiringStep` (wire);
`LocalInventoryProbes`, `InventorySnapshot`, `BrowserPresence`, `LocalInventory` (`items`,
`wiring`, `isChecking`, `refresh()`, `static items(from:)`, `static live(watcher:)`);
`AgentConnectPolicy.isAllowed(_:installRoot:binaries:)`; `AgentProcessRunning`,
`LiveAgentProcessRunner`; `AgentConnect.environment(_:binary:)`, `run(_:installRoot:binaries:runner:base:)
-> AgentConnectOutcome`, `failureMessage(status:stderr:)`.

- [ ] **Step 1: Wire model** — `Models/AgentWiring.swift`:

```swift
import Foundation

/// Mirror of `GET /agents/wiring` (Track I T3). Read-only facts plus the exact
/// argv the app may run after the person's click (`AgentConnect`).
struct AgentWiringStep: Codable, Hashable {
    let step: String
    let display: String
    let argv: [String]
    let touches: [String]
}

struct AgentWiring: Codable, Hashable, Identifiable {
    let id: String
    let installed: Bool
    let binary: String?
    let recall: String
    let autosave: String
    let connect: [AgentWiringStep]
    let detail: String?
}

struct AgentWiringResponse: Codable, Hashable {
    let agents: [AgentWiring]
    let python: String
    let repo: String
    let memory: String
}
```
  and in `APIClient.swift` (the MARK for intake): `func fetchAgentWiring() async throws ->
  AgentWiringResponse { try await get("/agents/wiring") }`.

- [ ] **Step 2: Failing tests.** `AgentConnectTests.swift`:

```swift
import XCTest
@testable import CicadaApp

final class RecordingRunner: AgentProcessRunning, @unchecked Sendable {
    var calls: [(argv: [String], env: [String: String])] = []
    var statuses: [Int32] = []
    var stderr = ""
    func run(_ argv: [String], environment: [String: String], timeout: Duration) async -> AgentProcessResult {
        calls.append((argv, environment))
        return AgentProcessResult(status: statuses.isEmpty ? 0 : statuses.removeFirst(), stderr: stderr)
    }
}

/// Track I T7 (R-IA28, D-1) — the app runs the wiring commands only after a
/// click, only if every one is a shape it recognises, with capture off.
final class AgentConnectTests: XCTestCase {
    private let root = URL(fileURLWithPath: "/R/cicada")
    private let claude = "/opt/bin/claude"
    private var python: String { root.path + "/api/.venv/bin/python" }

    private func mcpStep(_ bin: String? = nil) -> AgentWiringStep {
        let argv = [bin ?? claude, "mcp", "add", "cicada", "--scope", "user", "--env", "CICADA_MEMORY_PATH=/M/memory",
                    "--", python, root.path + "/mcp/server.py"]
        return AgentWiringStep(step: "mcp", display: argv.joined(separator: " "), argv: argv, touches: ["~/.claude.json"])
    }

    private func hookStep(settings: String = "/Users/x/.claude/settings.json") -> AgentWiringStep {
        let argv = [python, root.path + "/api/hooks/registry.py", "install", "--settings", settings, "--event", "Stop",
                    "--command", "\"\(python)\" \"\(root.path)/api/hooks/capture.py\" --harness claude-code"]
        return AgentWiringStep(step: "hook", display: argv.joined(separator: " "), argv: argv, touches: ["~/.claude/settings.json"])
    }

    func testTheTwoInstallShShapesAreAllowed() {
        XCTAssertTrue(AgentConnectPolicy.isAllowed(mcpStep().argv, installRoot: root, binaries: [claude]))
        XCTAssertTrue(AgentConnectPolicy.isAllowed(hookStep().argv, installRoot: root, binaries: [claude]))
        XCTAssertTrue(AgentConnectPolicy.isAllowed(hookStep(settings: "/Users/x/.codex/hooks.json").argv,
                                                   installRoot: root, binaries: [claude]))
    }

    func testAnythingElseIsRefused() {
        let refused: [[String]] = [
            ["/bin/rm", "-rf", "/"],
            [claude, "mcp", "remove", "cicada"],
            [claude, "mcp", "add", "other", "--", python, root.path + "/mcp/server.py"],
            ["/usr/local/bin/claude", "mcp", "add", "cicada", "--", python, root.path + "/mcp/server.py"],
            [claude, "mcp", "add", "cicada", "--", "/elsewhere/python", root.path + "/mcp/server.py"],
            [claude, "mcp", "add", "cicada", "--", python, root.path + "/mcp/server.py", "--extra"],
            [claude, "mcp", "add", "cicada", "--transport", "http", "--", python, root.path + "/mcp/server.py"],
            [python, root.path + "/api/hooks/other.py", "install"],
            [python, root.path + "/api/hooks/registry.py", "uninstall", "--settings", "/Users/x/.claude/settings.json"],
            [python, root.path + "/api/hooks/registry.py", "install", "--settings", "/etc/passwd", "--event", "Stop",
             "--command", "x api/hooks/capture.py --harness y"],
        ]
        for argv in refused {
            XCTAssertFalse(AgentConnectPolicy.isAllowed(argv, installRoot: root, binaries: [claude]), argv.joined(separator: " "))
        }
        XCTAssertFalse(AgentConnectPolicy.isAllowed(mcpStep().argv, installRoot: URL(fileURLWithPath: "/other"),
                                                    binaries: [claude]), "a backend from another checkout is refused")
    }

    func testCaptureIsOffKeysAreScrubbedAndTheBinaryIsOnPath() async {
        let runner = RecordingRunner()
        let outcome = await AgentConnect.run([mcpStep(), hookStep()], installRoot: root, binaries: [claude], runner: runner,
                                             base: ["PATH": "/usr/bin", "ANTHROPIC_API_KEY": "sk-x", "HOME": "/Users/x"])
        XCTAssertEqual(outcome, .done)
        XCTAssertEqual(runner.calls.count, 2)
        for call in runner.calls {
            XCTAssertEqual(call.env["CICADA_CAPTURE"], "off", "Cicada's own children are never captured (R8)")
            XCTAssertNil(call.env["ANTHROPIC_API_KEY"])
            XCTAssertEqual(call.env["HOME"], "/Users/x")
        }
        XCTAssertTrue(runner.calls[0].env["PATH"]!.hasPrefix("/opt/bin:"))
    }

    func testOneRefusedStepRunsNothingAndOffersTheCommandsToCopy() async {
        let runner = RecordingRunner()
        let foreign = AgentWiringStep(step: "mcp", display: "rm -rf /", argv: ["/bin/rm", "-rf", "/"], touches: [])
        let outcome = await AgentConnect.run([mcpStep(), foreign], installRoot: root, binaries: [claude], runner: runner, base: [:])
        XCTAssertEqual(outcome, .refused([mcpStep().display, "rm -rf /"]))
        XCTAssertTrue(runner.calls.isEmpty)
    }

    func testExitThreeIsTheUntouchedInvalidFileAndTheFirstFailureStops() async {
        let runner = RecordingRunner()
        runner.statuses = [3, 0]
        let outcome = await AgentConnect.run([hookStep(), mcpStep()], installRoot: root, binaries: [claude], runner: runner, base: [:])
        XCTAssertEqual(outcome, .failed(Copy.foundInvalidSettings))
        XCTAssertEqual(runner.calls.count, 1)
        XCTAssertEqual(AgentConnect.failureMessage(status: 1, stderr: "MCP server cicada already exists\nmore"),
                       "MCP server cicada already exists")
    }
}
```

  `LocalInventoryTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// Track I T7 (design §4.1.3) — detect, don't ask. Absent apps have no row;
/// a blocked Safari needs permission; backend-probed agents appear only once the
/// probe answers ("never blank" is the host's "Checking…" line).
@MainActor
final class LocalInventoryTests: XCTestCase {
    private func wiring(_ agents: [AgentWiring]) -> AgentWiringResponse {
        AgentWiringResponse(agents: agents, python: "/R/python", repo: "/R", memory: "/M")
    }
    private func agent(_ id: String, installed: Bool = true, recall: String = "off", autosave: String = "off",
                       steps: Int = 2) -> AgentWiring {
        AgentWiring(id: id, installed: installed, binary: installed ? "/bin/\(id)" : nil, recall: recall, autosave: autosave,
                    connect: (0..<steps).map { AgentWiringStep(step: "s\($0)", display: "d", argv: ["a"], touches: []) },
                    detail: nil)
    }

    func testRowsAppearOnlyForWhatIsHere() {
        let items = LocalInventory.items(from: InventorySnapshot(
            wiring: wiring([agent("claude-code"), agent("codex", installed: false)]),
            installedBundles: [LocalInventory.cursorBundleId],
            browsers: ["chrome-bookmarks": .off, "safari-bookmarks": .absent],
            claudeDesktopHasCicada: nil))
        XCTAssertEqual(items.map(\.id), [.agent("claude-code"), .agent("cursor"), .browser("chrome-bookmarks")])
    }

    func testStatesMapToReadiness() {
        let items = LocalInventory.items(from: InventorySnapshot(
            wiring: wiring([agent("claude-code", recall: "on", autosave: "on", steps: 0),
                            agent("codex", autosave: "invalid", steps: 1)]),
            installedBundles: [LocalInventory.claudeDesktopBundleId],
            browsers: ["chrome-bookmarks": .on, "safari-bookmarks": .blocked],
            claudeDesktopHasCicada: true))
        let byId = Dictionary(uniqueKeysWithValues: items.map { ($0.id, $0.readiness) })
        XCTAssertEqual(byId[.agent("claude-code")], .alreadyOn)
        XCTAssertEqual(byId[.agent("codex")], .failed(Copy.foundInvalidSettings))
        XCTAssertEqual(byId[.agent("claude-desktop")], .alreadyOn)
        XCTAssertEqual(byId[.browser("chrome-bookmarks")], .alreadyOn)
        XCTAssertEqual(byId[.browser("safari-bookmarks")], .needsPermission)
    }

    func testNoWiringYetMeansNoAgentRowsNotFalseOnes() {
        let items = LocalInventory.items(from: InventorySnapshot(wiring: nil, installedBundles: [],
                                                                 browsers: [:], claudeDesktopHasCicada: nil))
        XCTAssertTrue(items.isEmpty)
    }

    func testAgentsArePreTickedAndAppsThatOpenElsewhereAreNot() {
        let items = LocalInventory.items(from: InventorySnapshot(
            wiring: wiring([agent("claude-code")]), installedBundles: [LocalInventory.cursorBundleId],
            browsers: [:], claudeDesktopHasCicada: nil))
        XCTAssertEqual(items.filter(FoundPolicy.defaultOn).map(\.id), [.agent("claude-code")])
    }

    func testRefreshReadsTheProbesAgain() async {
        var chrome: BrowserPresence = .off
        let inventory = LocalInventory(probes: LocalInventoryProbes(
            wiring: { nil }, isInstalled: { _ in false }, browserPresence: { $0 == "chrome-bookmarks" ? chrome : .absent },
            claudeDesktopHasCicada: { nil }))
        await inventory.refresh()
        XCTAssertEqual(inventory.items.first?.readiness, .ready)
        chrome = .on
        await inventory.refresh()
        XCTAssertEqual(inventory.items.first?.readiness, .alreadyOn, "a Full Disk Access grant or a Turn on shows on the next scan")
    }
}
```

  `AgentWiringCatalogTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// Track I T7 (design §4.1.6) — the copy-paste snippets Settings → Agents shows
/// and the argv the app runs are the SAME commands. `api/tests/test_agent_wiring.py`
/// reads the same fixture, so a change on either side goes red here or there.
final class AgentWiringCatalogTests: XCTestCase {
    private struct Fixture: Decodable {
        struct Case: Decodable { let agent: String; let step: String; let argv: [String] }
        let root: String
        let memory: String
        let cases: [Case]
    }

    /// POSIX-ish splitting for the two snippets: single quotes (with the `'\''`
    /// idiom `SnippetEscape.shell` emits), double quotes with backslash escapes,
    /// and spaces.
    private func shellWords(_ s: String) -> [String] {
        var words: [String] = [], word = "", inWord = false, quote: Character? = nil, escape = false
        for c in s {
            if escape { word.append(c); escape = false; continue }
            if let q = quote {
                if c == q { quote = nil } else if c == "\\" && q == "\"" { escape = true } else { word.append(c) }
                continue
            }
            switch c {
            case "'", "\"": quote = c; inWord = true
            case "\\": escape = true; inWord = true
            case " ", "\n": if inWord { words.append(word); word = ""; inWord = false }
            default: word.append(c); inWord = true
            }
        }
        if inWord { words.append(word) }
        return words
    }

    func testTheSnippetsRunExactlyWhatTheAppWouldRun() throws {
        let repo = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let data = try Data(contentsOf: repo.appendingPathComponent("api/tests/fixtures/agent_wiring_argv.json"))
        let fixture = try JSONDecoder().decode(Fixture.self, from: data)
        XCTAssertEqual(fixture.cases.count, 2, "a table test over nothing passes vacuously")
        let catalog = AgentSetupCatalog.all(home: fixture.root, memoryRoot: fixture.memory)
        for c in fixture.cases {
            let setup = try XCTUnwrap(catalog.first { $0.id == c.agent }, c.agent)
            let command = try XCTUnwrap(setup.steps.first?.command, c.agent)
            XCTAssertEqual(shellWords(command), c.argv, c.agent)
        }
    }
}
```

  Run → compile failure. Red.

- [ ] **Step 3: `Support/AgentConnect.swift`:**

```swift
import Foundation

struct AgentProcessResult: Equatable {
    let status: Int32
    let stderr: String
}

protocol AgentProcessRunning: Sendable {
    func run(_ argv: [String], environment: [String: String], timeout: Duration) async -> AgentProcessResult
}

/// `Process`, never a shell: argv[0] is an absolute path the backend resolved,
/// and nothing is interpolated into a command string. 124 on timeout, 127 when
/// the binary cannot start — `run_cli`'s conventions (`connections/base.py`).
struct LiveAgentProcessRunner: AgentProcessRunning {
    func run(_ argv: [String], environment: [String: String], timeout: Duration) async -> AgentProcessResult {
        await withCheckedContinuation { continuation in
            let process = Process()
            process.executableURL = URL(fileURLWithPath: argv[0])
            process.arguments = Array(argv.dropFirst())
            process.environment = environment
            let errors = Pipe()
            process.standardError = errors
            process.standardOutput = FileHandle.nullDevice
            process.standardInput = FileHandle.nullDevice
            let lock = NSLock()
            var resumed = false
            func finish(_ result: AgentProcessResult) {
                lock.lock(); defer { lock.unlock() }
                guard !resumed else { return }
                resumed = true
                continuation.resume(returning: result)
            }
            process.terminationHandler = { done in
                let data = errors.fileHandleForReading.readDataToEndOfFile()
                finish(AgentProcessResult(status: done.terminationStatus, stderr: String(decoding: data, as: UTF8.self)))
            }
            do {
                try process.run()
            } catch {
                finish(AgentProcessResult(status: 127, stderr: error.localizedDescription))
                return
            }
            let seconds = Double(timeout.components.seconds) + Double(timeout.components.attoseconds) / 1e18
            DispatchQueue.global().asyncAfter(deadline: .now() + seconds) {
                if process.isRunning {
                    process.terminate()
                    finish(AgentProcessResult(status: 124, stderr: "timed out"))
                }
            }
        }
    }
}

enum AgentConnectOutcome: Equatable {
    case done
    /// Not run at all; these are the commands to copy (D-1's fallback).
    case refused([String])
    case failed(String)
}

/// Track I T7 (R-IA28) — the only two command shapes the app will run, pinned to
/// the checkout the app itself was built from (`BackendProcess.installRoot()`).
/// The backend hands the argv over (`GET /agents/wiring`), but a response the app
/// cannot vouch for — another checkout, another verb, one extra token — runs
/// nothing.
enum AgentConnectPolicy {
    static func isAllowed(_ argv: [String], installRoot: URL, binaries: Set<String>) -> Bool {
        let root = installRoot.standardizedFileURL.path
        let python = root + "/api/.venv/bin/python"
        guard let head = argv.first else { return false }
        if binaries.contains(head), ["claude", "codex"].contains(URL(fileURLWithPath: head).lastPathComponent) {
            guard argv.count >= 7, Array(argv[1...3]) == ["mcp", "add", "cicada"],
                  let dashes = argv.firstIndex(of: "--"),
                  Array(argv[(dashes + 1)...]) == [python, root + "/mcp/server.py"] else { return false }
            return argv[4..<dashes].allSatisfy { ["--scope", "user", "--env"].contains($0) || $0.hasPrefix("CICADA_MEMORY_PATH=") }
        }
        guard argv.count == 9, head == python, argv[1] == root + "/api/hooks/registry.py", argv[2] == "install",
              argv[3] == "--settings",
              argv[4].hasSuffix("/.claude/settings.json") || argv[4].hasSuffix("/.codex/hooks.json"),
              Array(argv[5...6]) == ["--event", "Stop"], argv[7] == "--command" else { return false }
        return argv[8].contains("api/hooks/capture.py") && argv[8].contains("--harness ")
    }
}

/// Track I T7 (spec decision 14, D-1) — the app registers the MCP server and the
/// Stop hook itself, after the person's click, with the exact commands shown to
/// them first (`FoundRow`'s disclosure = `display`). The same effect as
/// `install.sh:277-321`, and the only route a `.dmg` install will have.
enum AgentConnect {
    static let stepTimeout: Duration = .seconds(15)
    /// `connections/base.py::SCRUBBED_ENV_KEYS` — a child never inherits a key.
    static let scrubbedKeys = ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "GEMINI_API_KEY"]

    /// `CICADA_CAPTURE=off` so nothing Cicada runs is captured back as an episode
    /// (R8); the binary's own directory first on PATH, because a Finder-launched
    /// app's PATH is the bare system one.
    static func environment(_ base: [String: String], binary: String) -> [String: String] {
        var env = base
        for key in scrubbedKeys { env.removeValue(forKey: key) }
        env["CICADA_CAPTURE"] = "off"
        let dir = URL(fileURLWithPath: binary).deletingLastPathComponent().path
        env["PATH"] = dir + ":" + (base["PATH"] ?? "/usr/bin:/bin:/usr/sbin:/sbin")
        return env
    }

    static func failureMessage(status: Int32, stderr: String) -> String {
        if status == 3 { return Copy.foundInvalidSettings }
        let first = stderr.split(separator: "\n").map { $0.trimmingCharacters(in: .whitespaces) }.first { !$0.isEmpty }
        return first ?? Copy.intakeFailed
    }

    static func run(_ steps: [AgentWiringStep], installRoot: URL, binaries: Set<String>,
                    runner: AgentProcessRunning = LiveAgentProcessRunner(),
                    base: [String: String] = ProcessInfo.processInfo.environment) async -> AgentConnectOutcome {
        guard steps.allSatisfy({ AgentConnectPolicy.isAllowed($0.argv, installRoot: installRoot, binaries: binaries) }) else {
            return .refused(steps.map(\.display))
        }
        for step in steps {
            let result = await runner.run(step.argv, environment: environment(base, binary: step.argv[0]), timeout: stepTimeout)
            if result.status != 0 { return .failed(failureMessage(status: result.status, stderr: result.stderr)) }
        }
        return .done
    }
}
```

- [ ] **Step 4: `Support/LocalInventory.swift`:**

```swift
import AppKit
import Foundation

enum BrowserPresence: Equatable { case absent, blocked, off, on }

struct InventorySnapshot: Equatable {
    var wiring: AgentWiringResponse?
    var installedBundles: Set<String>
    var browsers: [String: BrowserPresence]
    var claudeDesktopHasCicada: Bool?
}

/// Everything detection touches, injected (design §12 T7: "LocalInventory with
/// injected probes"). The live set reads only local state — bundle ids, file
/// presence, one JSON key — and one loopback call; no outbound network.
struct LocalInventoryProbes {
    var wiring: () async -> AgentWiringResponse?
    var isInstalled: (String) -> Bool
    var browserPresence: (String) -> BrowserPresence
    var claudeDesktopHasCicada: () -> Bool?
}

/// Track I T7 (design §4.1.3) — detect, don't ask. Detect by bundle id, never
/// by name; an absent app has no row; a backend-probed row appears once the
/// probe answers. Part b's Welcome and this track's `+` strip share it.
@MainActor
@Observable
final class LocalInventory {
    nonisolated static let cursorBundleId = "com.todesktop.230313mzl4w4u92"
    nonisolated static let claudeDesktopBundleId = "com.anthropic.claudefordesktop"

    private(set) var items: [FoundItem] = []
    private(set) var wiring: AgentWiringResponse?
    private(set) var isChecking = false
    @ObservationIgnored var probes: LocalInventoryProbes

    init(probes: LocalInventoryProbes) { self.probes = probes }

    func refresh() async {
        isChecking = true
        let fetched = await probes.wiring()
        let snapshot = InventorySnapshot(
            wiring: fetched,
            installedBundles: Set([Self.cursorBundleId, Self.claudeDesktopBundleId].filter(probes.isInstalled)),
            browsers: Dictionary(uniqueKeysWithValues: BrowserWatchPolicy.watched.map { ($0.channel, probes.browserPresence($0.channel)) }),
            claudeDesktopHasCicada: probes.claudeDesktopHasCicada())
        wiring = fetched
        items = FoundPolicy.order(Self.items(from: snapshot))
        isChecking = false
    }

    nonisolated static func items(from s: InventorySnapshot) -> [FoundItem] {
        var out: [FoundItem] = []
        for (id, title) in [("claude-code", "Claude Code"), ("codex", "Codex")] {
            guard let a = s.wiring?.agents.first(where: { $0.id == id }), a.installed else { continue }
            let readiness: FoundItem.Readiness
            if a.recall == "on" && a.autosave == "on" { readiness = .alreadyOn }
            else if a.autosave == "invalid" { readiness = .failed(Copy.foundInvalidSettings) }
            else { readiness = a.connect.isEmpty ? .checking : .ready }
            out.append(FoundItem(id: .agent(id), group: .agents, title: title, isPresent: true,
                                 content: .ownIntentionalAct, readiness: readiness, opensAnotherApp: false))
        }
        if s.installedBundles.contains(cursorBundleId) {
            out.append(FoundItem(id: .agent("cursor"), group: .agents, title: "Cursor", isPresent: true,
                                 content: .ownIntentionalAct, readiness: .ready, opensAnotherApp: true))
        }
        if s.installedBundles.contains(claudeDesktopBundleId) {
            out.append(FoundItem(id: .agent("claude-desktop"), group: .agents, title: "Claude", isPresent: true,
                                 content: .ownIntentionalAct,
                                 readiness: s.claudeDesktopHasCicada == true ? .alreadyOn : .ready, opensAnotherApp: true))
        }
        for (channel, title) in [("chrome-bookmarks", "Chrome"), ("safari-bookmarks", "Safari")] {
            let readiness: FoundItem.Readiness
            switch s.browsers[channel] ?? .absent {
            case .absent: continue
            case .blocked: readiness = .needsPermission
            case .off: readiness = .ready
            case .on: readiness = .alreadyOn
            }
            out.append(FoundItem(id: .browser(channel), group: .browsers, title: title, isPresent: true,
                                 content: .ownIntentionalAct, readiness: readiness, opensAnotherApp: false))
        }
        return out
    }

    /// The live probes. The app reads `~/Library` (CLAUDE.md rail); the backend is
    /// asked only for what it alone can answer (the CLIs, via `/agents/wiring`).
    static func live(watcher: BrowserWatcher) -> LocalInventoryProbes {
        LocalInventoryProbes(
            wiring: { try? await APIClient.shared.fetchAgentWiring() },
            isInstalled: { NSWorkspace.shared.urlForApplication(withBundleIdentifier: $0) != nil },
            browserPresence: { channel in
                guard let file = BrowserWatchPolicy.file(for: channel),
                      let url = file.candidatePaths.first(where: { FileManager.default.fileExists(atPath: $0.path) })
                else { return .absent }
                // TCC answers an open, not a permission bit: `isReadableFile` says
                // yes to a Full-Disk-Access-protected file the app cannot read.
                guard let handle = try? FileHandle(forReadingFrom: url) else { return .blocked }
                try? handle.close()
                return watcher.isEnabled(channel) ? .on : .off
            },
            claudeDesktopHasCicada: {
                let url = FileManager.default.homeDirectoryForCurrentUser
                    .appendingPathComponent("Library/Application Support/Claude/claude_desktop_config.json")
                guard let data = try? Data(contentsOf: url) else { return nil }
                let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
                return (json?["mcpServers"] as? [String: Any])?["cicada"] != nil
            })
    }
}
```

- [ ] **Step 5: `Views/Intake/OnThisMacStrip.swift`** — the first `FoundRow` host (R-IA30):

```swift
import AppKit
import SwiftUI

/// Track I T7 — the `+` sheet's "On this Mac": what Cicada found, each with the
/// one action that turns it on. Agents run `AgentConnect` (D-1: after THIS click,
/// with the commands visible under the row's disclosure); browsers run
/// `BrowserWatcher.syncNow` (T1's consent); Cursor opens its own confirm via its
/// deep link; Claude Desktop is finished in Settings → Agents (slice 1).
struct OnThisMacStrip: View {
    @Environment(BrowserWatcher.self) private var watcher
    @State private var inventory: LocalInventory?
    @State private var states: [FoundItemID: FoundRowState] = [:]
    @State private var copyable: [FoundItemID: [String]] = [:]

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            Text(Copy.foundOnThisMac).font(CicadaTheme.headingFont).foregroundStyle(CicadaTheme.textPrimary)
            if let inventory {
                if inventory.items.isEmpty {
                    Text(inventory.isChecking ? Copy.foundCheckingApps : Copy.foundBackendDown)
                        .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                }
                ForEach(inventory.items) { item in row(item, wiring: inventory.wiring) }
            }
        }
        .task {
            let model = LocalInventory(probes: LocalInventory.live(watcher: watcher))
            inventory = model
            await model.refresh()
        }
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in
            Task { await inventory?.refresh() }
        }
    }

    @ViewBuilder
    private func row(_ item: FoundItem, wiring: AgentWiringResponse?) -> some View {
        let agent = wiring?.agents.first { if case .agent(let id) = item.id { return $0.id == id }; return false }
        let base: FoundRowState = {
            switch item.readiness {
            case .alreadyOn: return .on
            case .needsPermission: return .needsAction(Copy.foundAllow)
            case .failed(let why): return .failed(why)
            case .checking: return .working(Copy.foundCheckingApps)
            default: return .off
            }
        }()
        let disclosure = (agent?.connect ?? []).flatMap { [$0.display] + $0.touches.map { "Changes \($0)" } }
            + (agent == nil ? [] : [Copy.foundPastStays])
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            FoundRow(mark: Self.mark(item.id), title: item.title, detail: Self.detail(item.id),
                     state: states[item.id] ?? base, disclosure: disclosure,
                     action: { Task { await turnOn(item, agent: agent, wiring: wiring) } },
                     settingsLink: item.id == .agent("claude-desktop") ? .agents : nil)
            if let lines = copyable[item.id] {
                Text(Copy.foundRefused).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                ForEach(lines, id: \.self) { CommandBox(command: $0) }
            }
        }
    }

    static func mark(_ id: FoundItemID) -> FoundMark {
        switch id {
        case .agent("claude-code"): .logo("claude-code")
        case .agent("codex"): .logo("codex")
        case .agent("cursor"): .app(bundleId: LocalInventory.cursorBundleId, logo: "cursor", symbol: "cursorarrow")
        case .agent("claude-desktop"): .app(bundleId: LocalInventory.claudeDesktopBundleId, logo: "claude-desktop", symbol: "bubble.left")
        case .browser("chrome-bookmarks"): .app(bundleId: "com.google.Chrome", logo: "chrome", symbol: "globe")
        case .browser("safari-bookmarks"): .app(bundleId: "com.apple.Safari", logo: nil, symbol: "safari")
        default: .logo("")
        }
    }

    static func detail(_ id: FoundItemID) -> String {
        switch id {
        case .agent("cursor"): Copy.foundCursorDetail
        case .agent("claude-desktop"): Copy.foundClaudeDesktopDetail
        case .browser: Copy.foundBrowserDetail
        default: Copy.foundAgentDetail
        }
    }

    private func turnOn(_ item: FoundItem, agent: AgentWiring?, wiring: AgentWiringResponse?) async {
        switch item.id {
        case .agent("cursor"):
            let catalog = AgentSetupCatalog.all(home: wiring?.repo ?? BackendProcess.installRoot().path,
                                                memoryRoot: wiring?.memory)
            if let url = catalog.first(where: { $0.id == "cursor" })?.deeplink?.url { NSWorkspace.shared.open(url) }
        case .agent:
            guard let agent, let wiring else { return }
            states[item.id] = .working(Copy.foundConnecting)
            let outcome = await AgentConnect.run(agent.connect, installRoot: BackendProcess.installRoot(),
                                                 binaries: Set(wiring.agents.compactMap(\.binary)))
            switch outcome {
            case .done: states[item.id] = nil
            case .refused(let lines): states[item.id] = nil; copyable[item.id] = lines
            case .failed(let why): states[item.id] = .failed(why)
            }
            await inventory?.refresh()
        case .browser(let channel):
            if item.readiness == .needsPermission {
                NSWorkspace.shared.open(BrowserFileError.fullDiskAccessURL)
                return
            }
            states[item.id] = .working(Copy.foundSavingBookmarks)
            do {
                _ = try await watcher.syncNow(channel)
                states[item.id] = nil
            } catch {
                states[item.id] = .failed(AddSourceSheet.friendlyError(error))
            }
            await inventory?.refresh()
        default:
            return
        }
    }
}
```
  `AddSourceSheet.swift`, at the families level, under Task 7's root drop zone:
  `OnThisMacStrip().padding(.bottom, CicadaTheme.spacingMD)`.

- [ ] **Step 6: Green** — `swift build`, `swift test` (0 failures), the backend suite
  (`test_agent_wiring.py::test_the_shared_argv_fixture_matches` and `AgentWiringCatalogTests` both
  read `api/tests/fixtures/agent_wiring_argv.json`).

- [ ] **Step 7: Docs.** G117's status cell, append:

  > **Track I part a (2026-09-23):** the foundations the one-screen Welcome (part b) stands on — the F1 consent fix (a browser is read only after it is turned on), `GET /agents/wiring` (read-only), `LocalInventory` (detect by bundle id, injected probes), `AgentConnect` (the app registers the MCP server and the Stop hook after the person's click — spec decision 14 / D-1 — with `CICADA_CAPTURE=off` and an allowlist pinned to its own checkout; the backend never writes a harness root), and the tested pure halves `FoundPolicy`, `ScheduleHonesty` (ruling 4 made visible), `EngineReadiness`, `OnboardingFlow`, `HomeLayout`. The `+` sheet's *On this Mac* strip is their first host. F2 (a hand-off ends onboarding) retires with `FirstRunSheet` in part b (T8).

  `TODO.md` "Where things stand": one paragraph under the round-2 summary — "**Round 3, Track I
  part a** (`feat/intake-onboarding`): one intake for every chat export and every way a file arrives
  (sniff → preview → import → a card that never closes itself; `UploadOverlay` and the Feed's Upload
  button retired), consent before any browser read, the Gemini channel and the export-origin
  backfill, `GET /agents/wiring`, and the tested pure logic part b's Welcome and Home consume. Part b
  (T8 Welcome, T9 Home + ⌘1–7, T10 reminders, T11 docs, T12 live pass) is next." — and the test
  baselines line with the numbers this branch actually measured (never these placeholders' numbers).

- [ ] **Step 8: Commit** — stage the four new sources, `APIClient.swift`, `AddSourceSheet.swift`, the
  three new tests, `memory-evolution.md`, `TODO.md`;
  `git commit -m "feat(onboarding): On this Mac — detection and agent connect after a click (Track I T7, G117 D-1)" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"`.

---

## Not in scope

Named so a reviewer does not read an absence as an oversight.

- **Part b of this track** — T8 the Welcome (full window, sky band, name edit, `EngineChooser`
  embed, Start orchestration over `OnboardingFlow`, Set up later, rerun, retiring `FirstRunSheet`,
  `OwnerIdentityStep`, `OnboardingSleepStep` and `OnboardingSchedule`), **F2** (R-IA4), T9 Home +
  `AppTab.home` + ⌘1–7 (G108's ruling), the Getting started card, T10 reminders (`ExportWaits`, the
  evening reminder, the Feed waiting strip, "Remind me ▾"), T11 docs, T12 the live pass with
  screenshots. The seams they plug into exist: `IntakeRouter.accept/commit`, `IntakeOrigin.welcome/
  home/reminder/onboardingRow`, `FoundPolicy`, `LocalInventory`, `AgentConnect`, `ScheduleHonesty`,
  `EngineReadiness`, `OnboardingFlow`, `HomeLayout`, `MeadowPill`, `FoundRow`,
  `CicadaMotion.revealStagger`.
- **Track Z's use of the router** (`accept(urls:from: .sleepRoom)` on the worm) and every file under
  `Views/Sleep/` — including `SleepMood.swift:87`'s comment that still says "upload overlay" and
  `SleepView.swift`'s explicit `showsUpload: false`.
- **Track O's `EngineChooser` / `ConnectionLoginFlow`** — until then the done card links to Settings
  → Sleep (R-IA23). **Track S's `QuickMatch`** — the title filter is local `contains` (R-IA33).
  **Track E's `codex` engine** — `EngineReadiness` already maps `codex-cli`.
- **Moving staging into `api/services/episode_staging.py`** and the `processed_by` fix (D14) —
  Local-sources `1010fef` (R-IA5). **Claims already stamped `origin: claude-code`** from imported
  episodes are not rewritten (R-IA13).
- **The menu-bar status button as a drag target** (R-IA26), the **Downloads watch** (D-6 / T14),
  the **Claude Desktop JSON merge** (T13), the **skill copy** on any onboarding surface (G72 / R5 D2).
- **Hermes and Gemini CLI registration** (R-IA15 — Gemini CLI is read-only), **Grok / Perplexity /
  DeepSeek** parsers (R7 §1.5), speaker-aware evidence beyond the Gemini reply split (Track N,
  R-N2).
- **The Claude Code install hint** (`claude_cli.py:21`, design §9.4 / D-5) — waits on verifying the
  general-public installer line.
- **Bookmark counts in the `+` strip** (R-IA30) and the **F1b gate race reproduction** (needs a clean
  defaults domain — a throwaway macOS user, never the owner's keys).

---

## Verification the orchestrator runs at the end

1. `cd <worktree> && api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider` → **0
   failures** (≥ 2225 passed + this track's new tests). If only
   `test_agent_provenance.py::test_a_decay_only_change_lands_in_its_own_cicada_authored_commit` is
   red, re-run it alone and report both results.
2. `cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5` → success; `swift test 2>&1 | tail -20`
   → **0 failures** (≥ 1012 executed + the new tests); `cd <worktree> && node --test
   app/CicadaApp/Tests/graph/*.test.js` → 0 failures.
3. **Lints that must fail when broken:** add a literal `.animation(.easeIn(duration: 0.2))` to
   `Views/Intake/IntakePanel.swift` → `MotionLiteralLintTests` fails; add `.buttonStyle(.glassProminent)`
   to `Theme/MeadowPill.swift` → `LiquidGlassLintTests` fails; add `showsUpload: true` to
   `FeedView.swift` → `TopBarControlsTests` fails. Revert each and confirm green.
4. **Fixtures:** `cd <worktree> && api/.venv/bin/python api/tests/_intake_fixtures.py <scratchpad>/intake`
   writes the inputs below. Every live check uses them and a **throwaway memory created from the
   preview's Into → New memory…** (e.g. `intake-check`) — never the live bank. Afterwards confirm
   the active bank is still the owner's (Into never activates) and tell the owner the throwaway bank
   exists (there is no delete route yet — G87).
5. **Drop anywhere:** drag `claude-export.zip` over the Graph tab → the veil shows ("Drop to bring
   into Cicada" + three marks) and the drop reaches the overlay, **not** the canvas; the preview reads
   "Claude history", counts with a Jan–Mar 2026 range, "Skipped: users.json (…)"; Into → New memory →
   Import → the card shows the headline, "It isn't your active memory…" with Switch (do **not**
   switch), and stays open past 2 s. Drop it again into the same memory → "Nothing new". Drop the
   `chatgpt-export/` folder → skipped lines for `user.json`, `message_feedback.json`,
   `model_comparisons.json`, `shared_conversations.json` and `chat.html`, no error. Drop
   `claude-50.json` → "Bringing in 50 conversations…" then "Bringing in 50 of 50" (the job path).
6. **Every entry point:** ⌘⇧I and File → Import… open the panel idle; the menu-bar worm's *Import a
   file…* opens it and brings the window forward; dragging `gemini-takeout.zip` onto the **Dock icon**
   opens the preview ("Gemini activity", prompts) in the existing window, never a second one; Finder
   → `claude-export.zip` → Get Info → Open with still names the system's default, Cicada only in the
   list; the Feed has no Upload button; `+` → Chat exports shows three tiles with the Claude, ChatGPT
   and Gemini marks, each with Open export page and steps that never say "unzip"; the `+` root shows
   the drop zone and *On this Mac*.
7. **On this Mac, read-only on the owner's machine:** Claude Code reads **On** (install.sh already
   wired it); expand Codex's disclosure and compare the shown commands with `install.sh:277-321`'s
   shape. **Do not press Turn on for an agent on the owner's machine** without the owner's go-ahead —
   it writes `~/.codex/config.toml` and `hooks.json` (D-1 is yes, but a live check is not consent).
   Chrome reads **On** (its stored signature — R-IA2's migration); Settings → Integrations → Chrome
   → Sync now still works and the light reads Watching.
8. **Claude Desktop's config read (R-IA29):** open the `+` sheet with Claude Desktop installed; if
   macOS shows an "App Data" prompt, drop the probe (return `nil`) before merging and record it on
   G117.
9. **The owner's first real Gemini import** is the live check of R-IA9's prompt/reply split
   (synthetic fixtures model Takeout's documented cell; the owner's export is never read by an agent).
10. **Dark and light, 1.0× and 1.4× zoom:** the overlay scrolls inside itself at 1.4×, the Import
    pill reads (white on the day meadow, dark ink on the night meadow), marks nod once on hover, and
    Reduce Motion turns the nod into a ring and the veil into a cut.
11. **After merge and a backend restart (not before):** `GET /sources/overview` on the owner's bank
    shows a "Claude export" card where "Unattributed" held importer episodes, and `GET /contributors`
    shows one new `cicada` commit — the R-IA13 backfill. Read through the API only; never open the
    bank.
12. **The PR body states:** no sync domain added and no ETag recipe changed (`/sources/channels`
    gains a row, not a field; `VersionVector.swift` untouched); no price, token count or duration
    estimate on any surface; `/conversations/upload` is deprecated but unchanged in shape; the
    migration writes one `cicada`-authored commit per bank on first activation; the `turns` sidecar is
    byte-identical to `feat/provenance-viewer` `2a5ab0b` and collides by name with
    `feat/local-sources`' `turn_index` (the open question below).

---

## Cross-track seams (what each sibling needs to know)

| Track | Seam |
|---|---|
| Provenance (`feat/provenance-viewer`) | Task 2 Step 3 applies `2a5ab0b`'s `conversations.py` hunk byte-for-byte; a three-way merge sees identical changes. Its test file stays its own. |
| Local-sources (`feat/local-sources`) | `1010fef` rewrites `conversations.py:743-943` into wrappers over `api/services/episode_staging.py` and writes `turn_index`. Merge order decides who resolves; `intake.plan()` then calls its `scan`/`render`, and the `turns` / `turn_index` naming must be settled first (open question). Our import-line edits at the top of `conversations.py` are textual only. |
| Remote connector (`feat/remote-connector`) | `api/main.py`: we insert `agents,`/`intake,` and mount after `conversations`, away from its `remote` lines. |
| Mascot page (Track Z) | Calls `IntakeRouter.accept(urls:from: .sleepRoom)`; observes `phase`; `Store.intakeInFlight` semantics are now "a request in flight". `TopBarControls`' two parameters are inert until Z's rewrite drops them. |
| Settings v3 (Track O) | `EngineChooser` replaces the done card's Settings link (R-IA23); Settings → General gains part b's "Show setup checklist". |
| Search (Track S) | `QuickMatch` replaces the preview's `contains` filter (R-IA33). |
| Engines (Track E) | A connected `codex` candidate makes `EngineReadiness` answer `.ready(candidate: "codex")` with no change here. |
| Part b (T8–T12) | Consumes every Interfaces block above; nothing in this plan needs editing for it. |
