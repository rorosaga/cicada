# Round 4 — backlogs live in memory (G150) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The owner, 2026-09-24: *"this back and forth where i tell an agent to put it in the backlog, that backlog
itself i believe should go in cicada project memory, dont you think? with the brief task and an appended
notes/description and maybe some other things that might be relevant to how we show and store them. document this too
for now in the backlog and start working on it too."* Today "put it in the backlog" means an agent edits a markdown
table in some repository; the backlog is invisible to Cicada, to every other agent and to the person's own app. This
track makes a project's backlog first-class memory:

- **Stored in the bank** — one markdown file per item at `<bank>/backlog/<project-id>/<item-id>.md`: frontmatter for
  what a list needs, `## Description` for the reasoning, `## Notes` as an append-only log signed by whoever wrote each
  entry. Git-versioned, Obsidian-readable, agent-legible. Never an entity page.
- **Written by agents** through MCP (`cicada_add_backlog_item`, `cicada_add_backlog_note`; read with `cicada_backlog`),
  locally and remotely, and **by the person** in the app — every write through ONE module, `api/services/backlog.py`,
  scrubbed, committed alone with the house trailers, refused while Sleep runs.
- **Shown** on the Projects page: a Backlog section after Plan (text tabs Open · Doing · Done · All) whose rows open
  the item as the third column — title, state, triage, the description, the notes as a signed list, the moves, a note
  field. **Found** by ⌘K (a new FTS kind and a palette group). **Told** to agents: the primer's contract says what to
  do when the person says "put it in the backlog", its Current line counts each project's open items, and
  `cicada_project` lists the top ones.
- **Imported** — a markdown backlog in this repository's G-row shape (tables and `### G<n>` sections) files into a
  project's backlog keeping its ids and statuses, idempotently, through `POST /projects/{id}/backlog/import` or
  `scripts/import-backlog.sh`.

**Architecture:** A `progress.py`-shaped writer: `backlog.py` validates, scrubs, mints the id, renders and writes one
file, and returns the memory-relative paths; every caller (REST router, MCP tools, importer, demo) commits them itself
under its own author and trigger. Reads come from frontmatter through `bank_index` (lists) or one parse (an item). A
new `backlog` sync component (a stat walk, no parse) moves the ETags, `_state.md`'s inputs and the app's revalidation.
In the app, `BacklogCache` is an in-memory, ETag-revalidated cache like `ProjectsCache` — not a Store domain (R-PJ7's
precedent) — and every write is a `BacklogWrite` `Mutation` through `Store.perform`. Every decision in the app is a
pure function with a table test (`BacklogModel`); the views render what it returns.

**Tech Stack:** Python 3 / FastAPI / Pydantic (`api/`), the stdio MCP server (`mcp/server.py`) and the remote runtime
(`api/remote/`), SQLite FTS5 (`search_index.py`); SwiftUI + XCTest (`app/CicadaApp`); markdown + git bank.

**Binding sources:**

- The owner's request above, as relayed by the orchestrator with decisions R1–R7 (restated as rulings R-B1 … R-B27
  below — the brief's R-n map onto them and every place this plan decides beyond the brief says so).
- The round-4 brief and contracts (`ROUND4.md` in the orchestrator's session scratchpad, **not committed**):
  decisions D1 (model and effort per turn, joined at read) and D7 (portability and privacy), contracts C1–C3 (the
  per-turn sidecar's `model?`/`effort?`, claims' `recorded_ts`, the wire's `authorModel`/`authorEffort`). This track
  builds on none of them directly (they land from another track) and changes none of their shapes; R-B6 says how
  the notes meet them at merge.
- `CLAUDE.md`'s rails: markdown + git is the only truth; ETags ship with their client mapping (none here — no Store
  domain); Sleep-safety (no LLM anywhere in this track, every read engine-free); the privacy rule for docs;
  portability (no owner name, no author-machine path); secrets only in `~/.cicada/secrets.env`; every writer scrubs.
- `docs/goals/TODO.md` "Rulings that cost real work to derive" (binding; nothing here re-opens one — ruling 3 is the
  one this track leans on: the FTS rows are derived and disposable, the files are the truth).
- `docs/design/DESIGN_RULES.md` (Direction D) for every DR id cited; §9's dated rulings from DS-1 … PJ-5.
- `docs/superpowers/specs/2026-09-23-g141-project-timelines-design.md` and its rulings R-PJ*, R-PP* (the Projects
  page this track extends), G135's R-R* (remote scopes), G118 (provenance), G114 (the id rule).

Backlog rows: **G150** (new, this track), which builds **G13**'s per-project half (R-B27). Commits cite `G150` and
the DR ids they apply.

---

## What the code actually does today (verified at `feat/r4-backlog-in-memory` = `dev` @ `ecb59c7`)

**The one-writer precedent — `api/services/progress.py`.**
- `:1-15` — the module docstring: the ONE event writer; callers pass the ACTIVE bank's path and commit the returned
  `paths` themselves; nothing raises on a normal input, an error is `{"action": "error"}`.
- `:86-105` `_page` — resolves a subject through `id_utils.resolve_entity_file`, re-reads the real stem on a
  case-insensitive filesystem, never creates a page. `:108-115` `_zone` — the machine zone unless named.
- `:219-232` `_scrub` — `episode_scrub.scrub` + `episode_scrub.record(writer, n, bank=…)`.
- `:723-741` `write_note_episode` — the person's Log words as a companion episode (not reused here: a backlog note is
  its own file's text, never an episode — R-B1).

**The person's writes — `api/routers/projects.py`.**
- `:53-60` `_project_stem` — 404 for a missing, non-project or dropped page.
- `:125-126` `_write_lock = asyncio.Lock()`, `BUSY = "Sleep is writing this project, try again in a moment"`.
- `:136-140` `_guard` — `sleep_cycle.get_sleep_state().status == "running"` → 409.
- `:155-164` `_commit` — `git_service.build_commit_message(f"Project update {day}", [f"{p}: updated (source: n/a,
  trigger: user/companion_app)"], authors=["user"])` then `git_service.commit_paths`; a failed commit is logged, the
  write stands.
- `:80-91`, `:93-112` — the two GETs: `sync_service.etag_for(mp, "entities", "episodes", "inbox",
  extra=f"projects|{PROJECT_SHAPE}|{tz}")`, `sync_service.conditional`, `run_in_threadpool`.

**Commits and authors — `api/services/git_service.py`, `api/services/agent_commits.py`.**
- `git_service.py:142-191` `build_commit_message(subject, body_lines, authors=, sessions=, engine=)`.
- `:534-550` `commit_paths_sync` (named paths only, under the bank's write lock); `:1329-1334` `commit_paths` (async).
- `:302` `AUTHOR_SHAPE = "harness-1"`; `:406-412` `author_identity(author) -> (kind, provider)` — `user` → `user`,
  `cicada` → `system`, a harness label (`claude-code`, `claude-web`, `agent`) → `harness`.
- `agent_commits.py:29-35` `author_for(harness)` → the label, or `agent`; `:37-64` `commit_write(memory_path,
  subject=, lines=, paths=, author=, session=)` — commits only `paths`, refuses inside a running event loop, never
  raises.
- `api/services/source_overview.py:132-148` `HARNESS_LABELS` — the one harness → product-name map
  (`claude-code` → "Claude Code", `unknown` → "Other agents").

**MCP — `api/services/mcp_tools.py`, `mcp/server.py`, `api/remote/`.**
- `mcp_tools.py:78-168` `ToolContext` — `author` (`:121`), `trigger` = `mcp/<author>` or `remote/<author>` (`:125`),
  `commit_subject` "Agent write" / "Remote write" (`:129`), `can(tool)` (`:139`), `raw_excerpts` (the remote
  `sources` scope, `:113`), `sleep_running()` (`:163-168`, a loopback probe the suite pins to False —
  `api/tests/conftest.py:101-111`).
- `:171-180` `_demo_refusal`; `:891-925` `project` (`cicada_project`); `:967-1117` `note_progress` — the write-tool
  shape this track copies: validate → write → one `agentic_write` ledger row → `agent_commits.commit_write` unless
  Sleep runs.
- `mcp/server.py:175-621` `TOOLS` (the `cicada_note_progress` entry `:601-620`, the list closes `:621`);
  `:768-848` `handle_tool`; `:870-885` `_ctx()`; `:914-925` `handle_project`, `handle_note_progress`.
- `api/remote/catalog.py:29-55` — `TOOL_SCOPE`, `NEVER_REMOTE`, `WRITE_TOOLS`, `READ_TOOLS`.
  `api/remote/tools.py:30-45` `_tool(...)`; `:200-223` the remote `cicada_note_progress`; `:245` `tool_defs_for`.
  `api/remote/runtime.py:170-200` `_DISPATCH`; `:233-251` `call` — every `WRITE_TOOLS` member is already refused
  while Sleep runs (`BUSY_TEXT`) and in a demo bank, for every remote connection.
- `api/tests/test_remote_tools.py:39-75` — every stdio tool classified exactly once; nothing a connection is told
  names a tool it lacks (63 scope sets); write tools are not read-only. `api/tests/test_demo_capture.py:245-259` —
  `WRITES` must equal `catalog.WRITE_TOOLS`, and every write tool refuses a demo bank.

**The primer — `api/services/handshake.py`, `api/services/state_dictionary.py`.**
- `handshake.py:56` `CONTRACT_VERSION = 6`; `:71` `REMOTE_CONTRACT_VERSION = 4`; `:98-144` `_remote_contract(tools)`
  (each sentence gated on its tool, `:122-127` the note-progress one); `:205-226` `_CONTRACT` (item 3 "Save as you
  learn", item 7 "Never edit `entities/`, `hubs/` or `_index.md`"); `:291-383` `_now_block` — the project loop
  `:353-369` builds the `now:`/`next:` cursor under the `personal` gate.
- `state_dictionary.py:81` `SCHEMA_VERSION = 3`; `:95` `INPUT_COMPONENTS = ("entities", "inbox", "episodes",
  "bank")`; `:490-512` the project rows (`now`/`next` from `project_timeline.now_next`); `:590-599` `_cursor`.
- Measured on a freshly generated synthetic demo bank (2026-09-24): the primer is **1,229** of `MAX_TOKENS` 1,800
  (the contract alone 517), and `_state.md` is **6,115** of `MAX_BYTES` 6,144 — `_fit` trims people first when a
  project row grows.
- `api/tests/test_handshake.py:55-56` pins `CONTRACT_VERSION == 6`; `schema_version == 3` is pinned in FOUR places —
  `api/tests/test_state_v3.py:15`, `api/tests/test_state_dictionary.py:33` and `:251`, `api/tests/test_state_wiring.py:150`;
  `api/tests/test_handshake_r12.py:89-96` holds R12 per tool per scope set.

**`cicada_project` — `api/services/project_text.py`.** `:258-296` `render(timeline, state, *, memory_path, today,
raw, can_note, can_detail)` — one line per fact, the closing line names only tools the caller holds.

**Search — `api/services/search_index.py`, `api/services/search_service.py`.**
- `search_index.py:69` `SCHEMA_VERSION = "3"` (a bump rebuilds every index once); `:86` `INDEXED_SUBDIRS`;
  `:92-107` `_FTS_COLUMNS` / `WEIGHTS`; `:228-235` `_scan` (one level per subdir through `bank_index.files`);
  `:245-255` `_ordered` (`INDEXED_SUBDIRS.index(subdir)`); `:452-488` `_index_inbox` (the shape copied);
  `:491` `_INDEXERS`.
- `search_service.py:44` `KINDS`; `:45-51` `_KIND_ALIASES`; `:594-633` `_inbox_kind`; `:636-664` `_search_indexed`.
  `api/tests/test_search_service.py:147` pins the totals of an all-kinds search to exactly the five kinds of today.

**Sync — `api/services/sync_service.py:139-203`** `components()` (a dict of stamps; `bank_index.dir_stamp` is one
level deep, `api/services/bank_index.py:119-122`).

**Scrub — `api/services/episode_scrub.py:36-39`** `WRITERS` (an unknown writer is ledgered as `other`); `:83-99`
`scrub`; `:102-117` `record`.

**Demo — `api/services/demo_bank.py:101-129`** `populate` (the order: history, scenario, `_commit_scenario`,
`_expire_scenario`, `_write_scenario_events`, `_write_scenario_person`, `_write_scenario_followups`); `:717-764`
`_write_scenario_events` (writers called directly, one commit per author). `api/tests/_demo_scenario.py:22-49` —
`_STEPS`, `demo(...)`, `day_one(...)`. `api/tests/test_demo_bank.py:131-153` reads the two NEWEST commits as the
events' (`log.split(...)[:2]`), so a new demo step must commit before the events do.
`api/tests/test_projects_app_fixture.py` pins `app/CicadaApp/Tests/fixtures/projects-demo.json` byte for byte.

**The app.**
- `Views/Projects/ProjectsPage.swift:25` `@State private var card: String?`; `:80-89` the trailing slot (Reader, else
  the entity card); `:103-110` revalidation on a sync version event (`ProjectsRefresh`); `:111-114` a bank switch;
  `:160-171` `escape()` (Reader, card, project — DR-28); `:184-189` `openCard`/`closeCard`; `:193-198` `showList`;
  `:201-213` `openPendingProject` (read-then-clear `router.consumeProject()`).
- `Views/Projects/ProjectDetailColumn.swift:15, 20` `openCard`, `openEntity`; `:157-171` the Plan section and
  `.id("section.plan")`; `:172-178` Around; `:39, 44` `planEditing`, `typing` (L · M · D stand aside while a field
  is typed in); `:181-188` `section(_:title:meta:body:)`; `:266-274` `write(_:)`.
- `Views/Projects/ProjectBand.swift:26` `enum ProjectSection: String, CaseIterable, Sendable { case now, lately, plan,
  around }` — raw values persisted in `cicada.projects.collapsed` (`ProjectDetailColumn.swift:34`); no exhaustive
  switch over it anywhere.
- `Views/Projects/ProjectsCache.swift:1-127` — the cache this track's `BacklogCache` copies; `:129-139`
  `ProjectsRefresh`.
- `Views/Projects/ProjectSentence.swift:251-266` `StoryRowSurface` (a Projects row's hover/selected surface).
- `Views/Common/DetailHeader.swift` — a detail column's head with `displayFont(size: 22)` (DR-16's H1 role) and ×;
  reusing it adds no `displayFont` call site (DR-17). `Views/Common/TextTabs.swift:94-128` `AdaptiveTextTabs` (`nil`
  = All). `Views/Common/MarkdownBody.swift:42` `MarkdownBody(text:)`. `Views/Common/Tag.swift:6`
  `Tag(text:dot:)`. `Views/Contributors/ContributorsView.swift:291` `ContributorAvatar(author:kind:provider:size:)`
  (the real mark per author kind, DR-52). `Theme/Elevation.swift:21` `.columnEdge()` (a trailing column draws its
  own edge).
- `Sync/SyncAPI.swift:112-119` the Projects writes; `Services/APIClient.swift:2585-2640` their implementation, with
  `private` `post`/`patch` usable from another extension in the same file; `:2292` `getConditional`.
  `Services/ProjectsAPI.swift` — the protocol-plus-extension pattern for on-demand reads.
- `Tests/CicadaAppTests/StoreTests.swift:49` `FakeSyncAPI` (`@MainActor`, `writes`, `private func record`) — adding a
  `SyncAPI` requirement means adding it here too. `Tests/CicadaAppTests/ProjectsCacheTests.swift:6-32`
  `FakeProjectsAPI` (the fake this track copies).
- `Search/FindModels.swift:10-12` `FindKind`; `:24-59` `FindGroupID` (Int raw values, order = display order; never
  persisted — recents persist `FindRowKey`, whose kind is a String); `:97-113` `FindDestination`.
  `Search/FindServerRows.swift:6` `kinds`; `:8-16` `group(forKind:)`; `:22-28` `Context`; `:43-104` the hit switch.
  `Search/FindMerge.swift:94-178` `FindRowText` (two exhaustive switches). `Search/FindPaletteModel.swift:233-252`
  `runPass` builds the `Context`. `ContentView.swift:317-362` `openFind` (exhaustive over `FindDestination`).
  `Support/AppRouter.swift:76-92` `pendingProject` / `routeToProject` / `consumeProject`.
- `CicadaApp.swift:45, 156` and `ContentView.swift:49, 90-95` — `ProjectsCache` is created once, injected, and reset on
  a bank switch.
- Lints that scope the Projects files: `RelativeDayTests.swift:70-84` (no "Today"/"Yesterday"/"Tomorrow" literal under
  `/Views/Projects/`, `/Models/Project*`, `Copy+Projects.swift`), `ProjectBandTests.swift:160-180` (no "Timeline"
  literal there), `CountLiteralLintTests.swift:52-58` (a `Text("…\(n)…")` needs `UsageFormat`),
  `SelectionTintLintTests.swift:7-14` (a named file list — this track adds its two view files).

**Baselines (dev @ `ecb59c7`, 2026-09-24):** backend **3775 passed, 1 skipped**; Swift **2003 tests, 0 failures**;
graph JS **8/8**.

---

## Global Constraints

**Where you work.**

- Work ONLY in `<worktree>` = `<repo>/.worktrees/r4-backlog`, on branch `feat/r4-backlog-in-memory` (based on `dev` @
  `ecb59c7`). `<repo>` is the repository root; the orchestrator's brief gives both absolute paths, and every command
  below spells `<worktree>` out in full when you run it. The path is not written here: an author-machine path in a
  public repo is a portability defect (CLAUDE.md).
- Every shell command is `cd <worktree> && <cmd>` with the ABSOLUTE path (zoxide hijacks a relative `cd`; ignore its
  stderr warning). Never `grep --include=*.ext` (zsh globs it) — use `rg`.
- Python: `cd <worktree> && api/.venv/bin/python -m pytest <files> -q -p no:cacheprovider`; the full suite is
  `api/tests`.

**What you never touch.**

- NEVER read `<repo>/memory` (any bank), `~/.cicada`, `~/Library/Safari` or `~/.claude/projects`. Every fixture is
  synthetic: `alpha-project`, `bob-example`, `hana-example`, `rover-arm-project`, `example.com`. The repo's own
  `docs/goals/memory-evolution.md` may be read as a FORMAT reference only; the importer's tests use a synthetic file.
- Never import anything into a real bank. Never run `make dev`, `make install-app` or `swift run`, never launch or
  kill the Cicada app or the launchd backend — the owner's installed app is live; the orchestrator installs and
  live-checks at the end.
- Contract shapes (C1–C7 in the round-4 brief) are never changed here. If a task finds it needs one changed, stop and
  say so.

**How you verify.**

- Backend: `api/tests` must report 0 failures (3775 passed, 1 skipped on this base, plus this track's tests).
  `test_agent_provenance.py::test_a_decay_only_change_lands_in_its_own_cicada_authored_commit` is order-dependent;
  if it is the ONLY red, re-run it alone and report both results. Anything else red is yours.
- Swift: `cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5` must succeed; `swift test 2>&1 | tail -20` must
  report 0 failures (2003 on this base, plus this track's). `SleepViewModelTests` poll tests and the search-latency
  tests can flake under load — re-run them alone before calling one yours. SourceKit diagnostics naming OTHER
  worktrees are noise.
- Graph JS: `cd <worktree> && node --test app/CicadaApp/Tests/graph/*.test.js` (pass the glob) stays 8/8 (untouched).

**Git.**

- Never `git add -A`; stage named files only. Never commit `memory/`, `logs/`, `.claude/settings.json`, `api/.venv`
  or `*-report.md`. No push, no new branches or worktrees, no subagents. Ignore Devin and PR comments.
- End every commit message with the attribution lines your session's system reminder names. Each commit cites `G150`
  and, for app work, the DR ids it applies.

**Rails this track holds (CLAUDE.md).**

- **No LLM anywhere.** Every read and write here is file I/O and git; v1 extracts nothing from conversations (R-B3).
- **Scrub before write** (R-B10). **Portability**: no owner name, no machine path, in code, tests, docs or commits.
  `api/tests/test_owner_name_portability.py` fails on the owner's capitalised given name anywhere in shipped `api/`,
  `mcp/` or `skills/` — a docstring quoting the owner says "the owner, 2026-09-24", never his name (only a
  `docs/goals/` G-row uses the "<Name> <date>: …" voice).
- **Privacy in docs**: nothing personal about the owner or anyone in their life in `docs/goals/`, `CLAUDE.md`, this
  plan, a commit or a PR body. The owner's own words about the design may be quoted (the G-row voice).
- **Telemetry** is ids and enums only: a project id, an item id, an action enum — never a title, a description or a
  note.
- **App copy** is plain and friendly (DR-59); no prices or token counts anywhere; a service is named with its real mark
  (`ContributorAvatar` / `OriginMark`, DR-52).

**Tokens, type and motion (DESIGN_RULES).** Colours only from `CicadaTheme`; selection is `bgFocus` + a strong ring
(`StoryRowSurface`) or `bgSelected`, never the accent (DR-5, DR-22). Every size through `CicadaTheme.font(size:)` or a
named token and every dimension through `CicadaTheme.scaled(_:)` (DR-70); no new `displayFont` call site (DR-17 —
the item card uses `DetailHeader`). Every rounded rectangle through `CicadaTheme.shape(_:)` (DR-12); no `Divider()`
(DR-11); no shadow (DR-9/10). Durations only from `CicadaMotion`; a keyboard action never animates — wrap it in
`Instant.run { }` (DR-60). Every count through `UsageFormat.count` (DR-21); a view never writes `Text("…\(n)…")` —
words are composed in `Copy.Projects.Backlog` or `BacklogModel`. Relative day words come ONLY from `RelativeDay`
(DR-58); the word "Timeline" never appears in the Projects files (R-PP12's lint).

**Docstrings** explain WHY, citing the G-row (G150, G141, G135, G118, G114), this plan's ruling (R-B*) or a prior
track's ruling (R-PJ*, R-PP*, R-R*), matching the density of the files you touch. Line numbers above are from
`ecb59c7` and drift as tasks land — read the cited code before editing.

**Test snippets.** "Append to `XTests.swift`" means inside that file's existing test class, before its closing
brace. The Swift package is in Swift 5 language mode; a test that builds a `Store`, a cache or a view model is
`@MainActor`. Python tests import the helpers the suite already has (`_synthetic_bank`, `_demo_scenario`,
`_stdio_server`); the autouse fixtures in `api/tests/conftest.py` already pin the loopback Sleep probe, the agent
home and auth.

---

## Rulings (binding)

Each ruling is a decision this plan takes — restating the brief where it decided, and deciding where it left a
choice — with its reason, so no task re-opens it. Those marked **§9** are dated in DESIGN_RULES §9 by Task 7.

- **R-B1 — Storage (brief R1).** One markdown file per item at `<bank>/backlog/<project-id>/<item-id>.md`, written
  only by `api/services/backlog.py`. Frontmatter, in this key order: `id`, `title` (the brief task, one line, ≤ 200
  characters), `project` (the project page's id), `status` (`open | doing | done | dropped`), `triage` (`apply |
  research | decide`, omitted when unset), `paid: true` (the 💸 flag, omitted when false), `created`, `updated`,
  `added_by` (`user` | a harness label | `cicada`), `session` (omitted when unknown), `links: [{kind, ref}]` (`kind`
  one of `pr | commit | url | doc | entity`, omitted when empty), `order` (an integer, omitted unless set by hand),
  and last the `notes` sidecar (R-B4). Body: `## Description`, then `## Notes`. YAML is dumped with
  `allow_unicode=True` so the file reads in Obsidian as it was written. An item is **never an entity page**: tasks
  are not one of the ten entity types, Stage 1 never extracts one, it never decays or archives, and search, the
  graph and Sleep never read `backlog/` as a page.
- **R-B2 — Ids (brief R2).** An id is `<PREFIX><n>` with no separator, like a G-id (`ORC12`, `RAP3`, `G151`);
  `ID_RE = ^([A-Z]{1,6})(\d{1,6})([a-z]?)$`. The letter suffix exists only so an imported id like `G74a` survives;
  a minted id never carries one. The prefix is, in order: the project page's `backlog_prefix:` (1–6 letters, upper-
  cased); else the prefix most of the project's existing items share (ties alphabetical); else the name's initials —
  the first letter of up to four words, or the first three letters of a one-word name (`Orchard` → `ORC`, `Rover Arm
  Project` → `RAP`), ASCII letters only after NFKD folding, `T` when nothing is left. **The middle step is this
  plan's addition:** an imported G-row backlog must continue at `G<max+1>` without the backlog writer ever writing an
  entity page (R-B3). The number is max+1 over the prefix's existing file names (G114's lesson — a count collides
  after a gap), and the file is **claimed by an exclusive create** (`O_CREAT | O_EXCL`), retrying the next number,
  because the backend and every stdio MCP process mint against the same folder and check-then-write lets two of them
  take one number. The file name is the id; a frontmatter `id` that disagrees is ignored. Input ids are normalised
  (`rap3` → `RAP3`, `G074` → `G74`).
- **R-B3 — The writer never writes an entity page.** No `last_referenced` bump, no `backlog_prefix` write, no
  claim. A backlog write is one file and one commit, never races Sleep on an entity page, and cannot move a
  project's decay clock or the Projects wire (`projects-demo.json` stays byte-identical). Whether a backlog write
  should count as a mention of its project for decay is recorded as open in G150.
- **R-B4 — Notes are append-only.** A note is a `### <YYYY-MM-DD> · <who>` heading and its text under `## Notes`;
  `<who>` is "You", "Cicada", a harness's product name through `source_overview.HARNESS_LABELS`, else "An agent".
  The machine fields live in the frontmatter sidecar `notes: [{at, by, session?}]`, one entry per note in order —
  `at` is the UTC instant to the second (`2026-09-24T10:31:02Z`, C2's `recorded_ts` shape), `by` the author id. The
  writer only ever appends, so the sidecar zips onto the notes by position; a sidecar longer than the notes (a note
  deleted by hand) is ignored whole, and a note appended by hand past the sidecar reads by its heading words alone.
  Every heading of levels 1–3 inside a description or a note is demoted to `####`, so pasted markdown can never start
  a section or forge a note. A note is never edited in place: the file's git history is its edit log.
- **R-B5 — A status move is a signed note.** Moving an item (a note with `status`, or a PATCH of `status`) appends
  "Moved from open to done." under the mover's name, as the note's last line when a note came with it. Title,
  triage, `paid` and link edits write no note — git keeps them. The card's notes are therefore the item's whole
  signed history of state.
- **R-B6 — Authors, and the model/effort seam.** The app writes `added_by`/`by` = `user`; MCP writes the harness label
  (`agent_commits.author_for`, G135 R-R11 — never the person, remote or not); the importer writes `user` (the person
  ran it). **Model and effort are not on this branch** (round-4 D1/C1–C3 land from another track), so a note names
  its harness, as the brief says. Every note stores `at` and `session`, exactly what C3's join needs, and the wire
  already carries `authorModel` / `authorEffort` on each note (always null in v1) so the app renders "Claude Code ·
  Opus 5.5 · high effort" the moment they arrive. **Merge step (Reported §1):** once the C3 track is on `dev`, its one
  join helper is called in `routers/backlog._note` — a second implementation of C3's join here would drift from it.
- **R-B7 — One writer; callers commit (brief R3).** `backlog.py` never commits. The REST router commits each write
  alone (`git_service.commit_paths` over the item's own file) as `Backlog update <day>`, `Cicada-Author: user`,
  trigger `user/companion_app`; an import as `Backlog import <day>`, trigger `user/backlog_import` (a new trigger,
  added to CLAUDE.md's list by Task 7). MCP commits through `agent_commits.commit_write` — subject `Agent write` /
  `Remote write`, trigger `mcp/<harness>` / `remote/<harness>`, `Cicada-Session:` the conversation — with one
  ids-and-enums `agentic_write` ledger row (the `note_progress` shape). Manifest lines are `<path>: created|updated
  (source: n/a, trigger: …)`, so `parse_cycle_body` and `cicada_timeline` read them like any other.
- **R-B8 — No backlog write while Sleep runs, through any door.** REST answers 409 with its own sentence (the
  `routers/projects.py` precedent); the remote runtime already refuses every `WRITE_TOOLS` member; and the stdio
  tools refuse too ("Sleep is consolidating memory right now — try again in a minute. Nothing was written."). That
  last is a deliberate departure from `cicada_write_claim`, which writes and leaves its page dirty: a backlog file
  left dirty would be swept into Sleep's `git add -A` commit under a model's name (the G85 smear), and no Sleep step
  owns `backlog/` to make that right.
- **R-B9 — One row per idea.** Adding an item whose title, folded to lower case and single spaces, equals an `open`
  or `doing` item's in the same project is refused and names the item that holds it ("RAP3 already holds this — add
  what you found to it as a note"): REST 409, MCP one line pointing at `cicada_add_backlog_note`. Exact only, never
  fuzzy (the house rule). A `done` or `dropped` item never blocks (an idea can come back), and the importer is exempt
  (it keeps a file's rows as they are).
- **R-B10 — Everything is scrubbed.** Title, description, every note and every link `ref` go through
  `episode_scrub.scrub` before a byte is written, ledgered as writer `backlog` (added to `episode_scrub.WRITERS`). A
  description is exactly where a pasted key lands.
- **R-B11 — Dates.** `created`, `updated` and a note's heading day are the writer's day in the machine zone
  (`handshake.local_timezone()`, `when.zone`), like every G141 date; `at` is UTC. The wire serves absolute days and
  its `tzName`; every relative word is derived in the app (`RelativeDay`, DR-58) or printed beside its date by MCP.
- **R-B12 — A remote connection without `sources` never reads the person's own words.** R-R22's rail: in
  `cicada_backlog`'s output, a description the person added or a note they wrote reads "(the person's own words —
  this connection can't read them)". Titles are shown (an item's name, like a project's or a milestone's). Stdio and
  REST are unaffected.
- **R-B13 — The agent tools, with two additions to the brief's signatures.** `cicada_backlog(project, status?, item?)`
  — `status` also takes `all`, and the added optional `item` reads one item in full, because "add a note, never a
  second item" presupposes reading the row first. `cicada_add_backlog_note(item, note, status?)` — `item` is `RAP3` or
  `<project>/RAP3`; a bare id two projects share is refused with both addresses, never guessed.
  `cicada_add_backlog_item(project, title, description, triage?, paid?)` — the description is required and must say
  something (the contract's "the reasoning as the description"); the person's add in the app may leave it empty.
- **R-B14 — Projects only.** Items live under a `type: project` page that is not `dropped`; an `archived` project
  still takes items (its page exists). Nothing here ever creates a page (the `progress._page` rule), and the owner's
  own page is not a backlog in v1.
- **R-B15 — The importer (brief R6).** `api/services/backlog_import.py` reads table rows whose first cell is
  `<prefix><n>[a-z]?` (optionally followed by 💸) and `### <prefix><n> — Title` sections, for ONE prefix per run
  (default `G`, so a file's `R1` research rows are not filed). Cells split on unescaped `|` (`\|` is a literal pipe);
  the first cell is the id, the second the item, the last the status, the middle joined is the reasoning. The title
  is the item cell's first `**bold**` span (else the cell without emphasis or link markup); what surrounds it — the
  owner's quoted words, a date — opens the description, and a title past 200 characters is cut at a word with "…"
  while the full one opens the description. The status is the FIRST mark in the status cell: ✅ done; 🛠️ 🟡 🔬 doing;
  🔲 ❓ 🅿️ open; no mark and "merged", "closed" or a bare "—" → dropped; anything else open. Triage is the enclosing
  `## ` heading's first word when it is APPLY, RESEARCH or DECIDE, else ❓ → decide and 🔬 → research. `paid` is 💸
  in the id cell or the section heading. `created` is the first ISO date in the item cell or section heading, else
  the enclosing `## ` heading's, else the import day. `PR #n` references become `pr` links. The first note, signed by
  whoever imported, keeps the raw status cell ("Imported from a backlog file. Its status there: …") so nothing the
  file said is lost. **An id already on the backlog is skipped, never updated** (the bank copy may hold notes the
  file does not) — so a second run changes nothing and makes no commit. One `Backlog import` commit, or none. The
  REST route (`POST /projects/{id}/backlog/import`, body `{markdown, prefix}`, 409 while Sleep runs) is the live path;
  `scripts/import-backlog.sh <bank-dir> <project-id> <file> [prefix]` runs the same module in-process on a named bank
  for a bank the backend is not consolidating (the orchestrator's synthetic check; the owner's real import after
  merge).
- **R-B16 — The sync component, `_state.md` v4 and the primer (brief R4).** `sync_service.components()` gains
  `backlog` = `backlog.stamp()` — project folders, item files and the newest mtime, a stat walk two levels deep with
  no parse. `state_dictionary.INPUT_COMPONENTS` gains it and `SCHEMA_VERSION` becomes 4: a project row carries
  `backlog_open: n` (items `open` or `doing`) only when n > 0, so a bank with no backlog renders byte-identically
  apart from the schema number. `_cursor` and the primer's Current row add " · backlog: n open", the primer under the
  same `personal` gate as `now`/`next` (G140's ruling: a record-only connection gets no profile). `_fit` is
  unchanged.
- **R-B17 — Contract versions (brief R5).** `CONTRACT_VERSION` 6 → 7 (item 3 names the three tools; item 7 adds
  `backlog/` to "never edit directly") and `REMOTE_CONTRACT_VERSION` 4 → 5 (a gated sentence per tool, and
  `cicada_backlog(project)` among the reads). **Merge rule:** if another round-4 track has bumped either on `dev`,
  take the next integer past it — the G138/G140 precedent.
- **R-B18 — On-demand reads, not Store domains.** `GET /projects/{id}/backlog` and `GET /backlog/{project}/{item}`
  ETag over `backlog` + `entities` (the project's name and prefix) with `extra` = `backlog|<list|item>|…|
  BACKLOG_SHAPE|AUTHOR_SHAPE|<machine zone>` — `AUTHOR_SHAPE` because the body carries an author kind (the G118
  rule), the zone because `lastNoteDay` is a day in it; never today. No `VersionVector` mapping, so the
  ship-together rule has nothing to pair. The app's `BacklogCache` lives in memory, revalidates with `If-None-Match`
  when the page appears, an item opens, a write lands, or a sync event moves `backlog`, `entities` or `bank`
  (`BacklogRefresh`), and empties on a bank switch (ids repeat across banks).
- **R-B19 — §9 — The Backlog section (brief R4).** It sits after Plan and before Around this project, collapsible and
  remembered like the others (`ProjectSection.backlog`, DR-39). Text tabs **Open · Doing · Done · All** (DR-45); a
  dropped item shows only under All — the "resting projects only under All" precedent (R-PP6). The brief's "count in
  the eyebrow" is the tabs' counts while the section is open and "n open" beside its label while it is folded (the
  section header's own rule, DR-38). The tab starts on the first of Open, Doing, Done that holds anything, until the
  viewer picks one. Rows keep the server's order: a hand-set `order` first, then the most recently touched, then the
  highest number. A row is its id (`metaFont`, `textTertiary`, tabular — never monospace, DR-19), its title
  (`rowFont`), a triage `Tag` and a "Paid AI" `Tag` when set (DR-44), and the age of its last note, else of the item
  (`RelativeDay.compactAge`, the full date in `.help`, DR-58); under All it also says its state in words. "Add to
  backlog" opens a title field and an optional "why" field; the new item opens in the third column.
- **R-B20 — §9 — The item card.** `DetailHeader` (the H1 role, DR-16, no new `displayFont` call site, DR-17) with a
  checklist glyph and "Added by <who> · <day>"; state, triage and "Paid AI" as `Tag`s; the moves as `NeutralButton`s
  — open: Start · Mark done · Drop; doing: Mark done · Drop; done and dropped: Reopen — and "Edit title" as a
  `TextButton`, all disabled with the reason while Sleep writes (DR-40, DR-41); the Description and each note render
  through `MarkdownBody` as page prose — **not** `quoteFont`: DR-18's door is for words someone *said* in a
  conversation, and a note is a written document that may hold lists and code; each note opens with its author's real
  mark (`ContributorAvatar`, DR-52) and words ("You", "Claude Code", "Claude Code · Opus 5.5 · high effort" when the
  wire carries the turn's model and effort), and its day through `RelativeDay.phrase` (full date in `.help`); Links as
  rows (a `url` is an `InlineLink`, the rest words); last, "Add a note". Editing a description, triage, links or
  order in the app is not v1 (the REST PATCH takes triage, `paid` and links for agents and scripts; Not in scope).
- **R-B21 — §9 — One trailing slot.** The Projects page's third column holds the Reader, else a backlog item, else an
  entity's card (`ProjectTrailing`); opening one replaces the other, and opening an item closes a Reader the old
  selection opened (DR-29). Esc closes the Reader, then the item or card, then the project (DR-28); "‹ N projects"
  closes the rightmost the same way (DR-27).
- **R-B22 — Only a status move is painted before the server answers.** Its result is known (R-PP19's rule); an add
  or a note shows when the server's answer lands (the id and the note's day are the server's). A failure rolls the
  paint back and toasts: a 409's own sentence (Sleep is writing, or the idea is already filed), else the page's words
  — a 400's or 404's detail names fields and ids (DR-54).
- **R-B23 — §9 — No `cicada.design.focus` flag (DR-73).** R-DS1's reasons hold unchanged; comparison is the
  installed build against the branch on a freshly generated demo bank.
- **R-B24 — §9 — An item's id is shown, as a G-id is (a DR-54 departure).** DR-54 keeps machine ids in `.help`; a
  backlog id is not a machine id but the address the person and agents cite in commits and conversation ("cite
  `G74a` the way you would cite a ticket"), so it is on the row and in the card's `.help` with the file path.
- **R-B25 — ⌘K.** A new FTS table `blg` (title, the id as its alias, project + status + triage as keywords, the
  description and notes as body; `ref` = `<project>/<id>`; `SCHEMA_VERSION` "3" → "4" rebuilds every index once), a
  `backlog` kind in `/search` (tokens required, like the inbox; a dropped item ranks after every live one), and a
  palette group "Backlog" after Inbox, fed by the server tier only — the local `QuickIndex` is built from Store
  snapshots and the backlog is not one. A row lands on Projects with the project open and the item in the third
  column (`AppRouter.routeToBacklogItem`).
- **R-B26 — The demo gains a backlog.** `demo_bank.populate` files five synthetic items on `rover-arm-project`
  (RAP1–RAP5: one each done and dropped, two open, one doing; notes from the person and from `claude-code`) — the
  items oldest first, then the notes oldest first, each with its own pinned `now` — each write committed at once
  under its own author — so an item touched by both keeps exact provenance —
  and **before** the scenario's events are written, so `test_demo_bank.py`'s newest-two-commits reading holds.
  `_demo_scenario.demo(backlog=True)` gains the flag and `day_one(...)` turns it off (PJ-1's expectations stay).
  `projects-demo.json` must stay byte-identical (R-B3); the Swift tests read a new fixture, `backlog-demo.json`,
  generated from the same demo and pinned by one pytest (R-PP27's precedent).
- **R-B27 — G150 is a new row that builds G13's per-project half.** CLAUDE.md says to edit a row rather than open a
  second one, and G13 ("Application-wide tasks/ideas backlog") already names this idea. The brief asks for a new
  G150; the precedent is G95 → G134 (a build row for a slice of an older idea). G13 is edited to point at G150 and
  keeps what G150 does not build: the application-wide board across projects, Sleep capture of undated "we should…"
  items, and the dogfood demo.

---

## File map

| File | Responsibility |
|---|---|
| `api/services/backlog.py` (new) | The ONE reader/writer: `Item`, `Note`; `project_page`, `initials`, `prefix_for`, `next_number`, `normalize_id`, `resolve_item`; `add_item`, `add_note`, `update_item`; `list_items`, `get_item`, `counts`, `open_counts`; `who_label`, `author_of`, `local_day`, `commit_message`, `stamp`, `parse_body` |
| `api/services/backlog_import.py` (new) | R-B15: `parse`, `status_of`, `import_markdown`, `import_file` |
| `api/routers/backlog.py` (new) | The six REST routes, their ETags, the 409 guard, the commits |
| `api/models/schemas.py` | `BacklogLink`, `BacklogNoteModel`, `BacklogItemSummary`, `BacklogItemModel`, `BacklogListResponse`, `BacklogItemCreate`, `BacklogNoteCreate`, `BacklogItemPatch`, `BacklogImportRequest`, `BacklogImportResponse` |
| `api/main.py` | mount the router |
| `api/services/sync_service.py` | the `backlog` component |
| `api/services/episode_scrub.py` | `WRITERS` gains `backlog` |
| `api/services/mcp_tools.py` | `backlog`, `add_backlog_item`, `add_backlog_note`; `project` passes the open items |
| `mcp/server.py` | three tool schemas, dispatch, handlers |
| `api/remote/catalog.py`, `api/remote/tools.py`, `api/remote/runtime.py` | scopes, remote schemas, dispatch |
| `api/services/handshake.py` | contract item 3 and 7, remote sentences, the Current row's count, versions |
| `api/services/state_dictionary.py` | schema v4, `backlog_open`, the `backlog` input |
| `api/services/project_text.py` | `cicada_project`'s backlog line |
| `api/services/search_index.py`, `api/services/search_service.py` | the `blg` table and the `backlog` kind |
| `api/services/demo_bank.py` | `_write_scenario_backlog` |
| `scripts/import-backlog.sh` (new) | R-B15's operator entry point |
| `api/tests/test_backlog_store.py`, `test_backlog_router.py`, `test_backlog_import.py`, `test_backlog_tools.py`, `test_backlog_search.py`, `test_backlog_app_fixture.py` (new) | the backend's tests |
| `api/tests/_demo_scenario.py`, `test_demo_capture.py`, `test_handshake.py`, `test_handshake_r12.py`, `test_state_v3.py`, `test_state_dictionary.py`, `test_state_wiring.py`, `test_search_service.py` | flags and pins this track moves |
| `app/CicadaApp/Tests/fixtures/backlog-demo.json` (new, generated) | the demo's backlog wire |
| `app/…/Models/ProjectBacklog.swift` (new) | the wire types, `BacklogStatus`, `BacklogModel` (pure) |
| `app/…/Services/BacklogAPI.swift` (new) | the two reads, `APIClient.backlogPath` |
| `app/…/Views/Projects/BacklogCache.swift` (new) | the in-memory cache, `BacklogRefresh` |
| `app/…/Sync/BacklogMutations.swift` (new) | `BacklogChange`, `BacklogWrite`, `BacklogWriteFailure` |
| `app/…/Sync/SyncAPI.swift`, `app/…/Services/APIClient.swift` | the three writes |
| `app/…/Theme/Copy+Projects.swift` | `Copy.Projects.Backlog` |
| `app/…/Views/Projects/ProjectBacklogSection.swift` (new) | the section |
| `app/…/Views/Projects/BacklogItemColumn.swift` (new) | the item card |
| `app/…/Views/Projects/ProjectTrailing.swift` (new) | the trailing slot and the Esc order (pure) |
| `app/…/Views/Projects/ProjectsPage.swift`, `ProjectDetailColumn.swift`, `ProjectBand.swift` | the slot, the section, `ProjectSection.backlog` |
| `app/…/CicadaApp.swift`, `app/…/ContentView.swift` | inject and reset `BacklogCache`; route a palette landing |
| `app/…/Search/FindModels.swift`, `FindServerRows.swift`, `FindMerge.swift`, `FindPaletteModel.swift`, `app/…/Support/AppRouter.swift` | the palette group and its landing |
| `app/…/Tests/CicadaAppTests/ProjectBacklogTests.swift`, `ProjectBacklogViewTests.swift` (new); `StoreTests.swift`, `FindServerTests.swift`, `SelectionTintLintTests.swift` | the app's tests |
| `docs/goals/memory-evolution.md`, `docs/goals/TODO.md`, `CLAUDE.md`, `docs/design/DESIGN_RULES.md` | G150, G13's pointer, the handoff line, the paragraph, the §9 lines |

`app/…` is `app/CicadaApp/Sources/CicadaApp`.

---

### Task 1: The store and the one writer — no route, no tool, no UI (G150 R-B1 … R-B11, R-B14, R-B16's component)

Everything a backlog *is* lands first, as a module with a table of tests, so every later task is a caller. The branch
stays shippable: nothing calls the module yet except the `backlog` sync component, which only adds a stamp.

**Files:**
- Create: `api/services/backlog.py`
- Modify: `api/services/episode_scrub.py:36-39` — `WRITERS` gains `"backlog"`
- Modify: `api/services/sync_service.py:139-203` — the `backlog` component
- Test: `api/tests/test_backlog_store.py` (new)

**Interfaces:**
- Produces (used by every later task): `backlog.BACKLOG_DIR`, `STATUSES`, `OPEN_STATUSES`, `TRIAGES`, `LINK_KINDS`,
  `USER`, `CICADA`, `TITLE_CHARS`, `BACKLOG_SHAPE`, `ID_RE`; dataclasses `Note(day, who, text, by, at, session)` and
  `Item(id, project, title, status, triage, paid, created, updated, added_by, session, links, order, description,
  notes, note_count, last_note_at, last_note_by)` with `Item.path`; `project_page(memory_path, project) -> (stem, fm)
  | dict`; `initials(name)`; `prefix_for(memory_path, stem, fm)`; `next_number(memory_path, stem, prefix)`;
  `normalize_id(raw)`; `item_path(memory_path, stem, item)`; `resolve_item(memory_path, ref, project=None) ->
  (stem, id) | dict`; `add_item(...)`, `add_note(...)`, `update_item(...)` → `{action, item, paths}` or a refusal;
  `list_items(memory_path, stem)`, `get_item(memory_path, stem, item)`, `counts(items)`, `open_counts(memory_path)`;
  `who_label(by)`, `author_of(note)`, `local_day(at, tz_name)`, `status_line(old, new)`, `parse_body(body)`,
  `commit_message(paths, *, action, subject, trigger, day, author, session)`, `stamp(memory_path)`.
- Consumes: `id_utils.resolve_entity_file`, `markdown_parser.parse`, `bank_index.files`, `episode_scrub.scrub` /
  `record`, `when.zone` / `utc_z` / `parse_instant`, `handshake.local_timezone`, `source_overview.HARNESS_LABELS`,
  `git_service.build_commit_message`.

- [ ] **Step 1: Failing tests.** Create `api/tests/test_backlog_store.py`:

```python
"""G150 — the backlog store: one markdown file per item, one writer (R-B1 … R-B11, R-B14).

Synthetic only: `alpha-project` and friends from `_synthetic_bank`, a fake key, example.com."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from _synthetic_bank import _bank, _entity
from api.services import backlog, bank_index, episode_scrub, markdown_parser, sync_service

NOW = datetime(2026, 9, 24, 10, 31, 2, tzinfo=timezone.utc)
SECRET = "sk-" + "A1b2C3d4E5f6G7h8J9k0"


@pytest.fixture
def bank(tmp_path):
    memory = _bank(tmp_path, git=False)
    bank_index.invalidate()
    return memory


def _add(bank, title="Cache the timeline per project", **kw):
    project = kw.pop("project", "alpha-project")
    kw.setdefault("description", "Opening a big project is slow; `_tree` re-reads every page.")
    kw.setdefault("author", "claude-code")
    kw.setdefault("now", NOW)
    kw.setdefault("tz_name", "UTC")
    return backlog.add_item(bank, project=project, title=title, **kw)


def _note(bank, item, note, **kw):
    kw.setdefault("author", "user")
    kw.setdefault("now", NOW)
    kw.setdefault("tz_name", "UTC")
    return backlog.add_note(bank, project=kw.pop("project", "alpha-project"), item=item, note=note, **kw)


def _snapshot(folder: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(folder.glob("*.md"))}


def _file(bank, item_id, project="alpha-project") -> Path:
    return bank / "backlog" / project / f"{item_id}.md"


def test_an_item_is_one_markdown_file_beside_its_project_and_no_page_moves(bank):
    before = _snapshot(bank / "entities")
    result = _add(bank, session="ses_abc", triage="apply", links=[{"kind": "pr", "ref": "#101"}])
    assert result["action"] == "added" and result["paths"] == ["backlog/alpha-project/AP1.md"]
    parsed = markdown_parser.parse(_file(bank, "AP1"))
    fm = parsed.frontmatter
    assert list(fm)[:4] == ["id", "title", "project", "status"]
    assert fm["id"] == "AP1" and fm["project"] == "alpha-project" and fm["status"] == "open"
    assert fm["triage"] == "apply" and fm["added_by"] == "claude-code" and fm["session"] == "ses_abc"
    assert fm["created"] == fm["updated"] == "2026-09-24" and fm["links"] == [{"kind": "pr", "ref": "#101"}]
    assert "paid" not in fm and "notes" not in fm and "order" not in fm
    assert parsed.body.startswith("## Description\n\nOpening a big project is slow")
    assert parsed.body.rstrip().endswith("## Notes")
    assert _snapshot(bank / "entities") == before        # R-B3: never an entity page


def test_ids_are_max_plus_one_per_prefix_never_a_count(bank):
    assert _add(bank, "First")["item"].id == "AP1"
    assert _add(bank, "Second")["item"].id == "AP2"
    _file(bank, "AP1").unlink()                                          # a gap
    _file(bank, "AP7").write_text("---\nid: AP7\ntitle: By hand\nproject: alpha-project\nstatus: open\n---\n\n"
                                  "## Description\n\nx\n", encoding="utf-8")   # a hand-made item
    assert _add(bank, "Third")["item"].id == "AP8"


def test_a_number_taken_between_the_scan_and_the_create_goes_to_the_next(bank, monkeypatch):
    _add(bank, "First")
    monkeypatch.setattr(backlog, "next_number", lambda *a, **k: 1)   # a racing process already took AP1
    assert _add(bank, "Second")["item"].id == "AP2"


@pytest.mark.parametrize("name,prefix", [("Orchard", "ORC"), ("Rover Arm Project", "RAP"), ("alpha", "ALP"),
                                         ("Café Órbita", "CO"), ("a b c d e", "ABCD"), ("42", "T"), ("", "T")])
def test_initials(name, prefix):
    assert backlog.initials(name) == prefix


def test_the_page_prefix_wins_then_the_items_own_then_the_initials(bank):
    assert _add(bank, "One")["item"].id == "AP1"                        # "Alpha Project"
    for n in (12, 13):                                                   # an imported sequence
        backlog.add_item(bank, project="alpha-project", title=f"Imported {n}", author="user", item_id=f"G{n}",
                         now=NOW, tz_name="UTC")
    assert _add(bank, "Two")["item"].id == "G14"                         # most items share G
    _entity(bank, "alpha-project", type="project", backlog_prefix="alp")
    assert _add(bank, "Three")["item"].id == "ALP1"                      # the page says so


def test_input_ids_are_normalised(bank):
    assert backlog.normalize_id(" rap3 ") == "RAP3"
    assert backlog.normalize_id("G074a") == "G74a"
    assert backlog.normalize_id("../x") is None and backlog.normalize_id("RAP") is None


@pytest.mark.parametrize("project,title,kw,action", [
    ("no-such-project", "x", {}, "not_found"),
    ("bob-example", "x", {}, "not_found"),                                # a person, not a project
    ("alpha-project", "   ", {}, "error"),
    ("alpha-project", "x", {"triage": "someday"}, "error"),
    ("alpha-project", "x", {"links": [{"kind": "tweet", "ref": "y"}]}, "error"),
    ("alpha-project", "x", {"status": "blocked"}, "error"),
])
def test_a_refusal_writes_nothing(bank, project, title, kw, action):
    assert _add(bank, title, project=project, **kw)["action"] == action
    assert not (bank / "backlog").exists()


def test_a_dropped_project_takes_no_items_and_an_archived_one_does(bank):
    _entity(bank, "beta-project", type="project", status="dropped")
    assert _add(bank, "x", project="beta-project")["action"] == "not_found"
    assert _add(bank, "x", project="gamma-project")["action"] == "added"   # archived: the page exists (R-B14)


def test_one_row_per_idea_an_open_title_is_not_filed_twice(bank):
    first = _add(bank, "Cache the timeline")["item"]
    again = _add(bank, "  cache THE   timeline ")
    assert again["action"] == "duplicate" and again["item_id"] == first.id and again["project"] == "alpha-project"
    assert "add what you found to it as a note" in again["error"]
    assert len(list((bank / "backlog" / "alpha-project").glob("*.md"))) == 1
    backlog.update_item(bank, project="alpha-project", item=first.id, status="done", author="user", now=NOW,
                        tz_name="UTC")
    assert _add(bank, "Cache the timeline")["action"] == "added"         # a done idea can come back (R-B9)


def test_notes_append_signed_and_a_status_move_is_a_note(bank):
    item = _add(bank)["item"]
    _note(bank, item.id, "Found it: `_tree` re-reads pages.", status="doing", author="claude-code", session="ses_abc")
    _note(bank, f"{item.id}".lower(), "Ship it Friday.", now=NOW.replace(day=25))
    got = backlog.get_item(bank, "alpha-project", item.id)
    assert got.status == "doing" and got.updated == "2026-09-25"
    assert [(n.day, n.who, n.by) for n in got.notes] == [("2026-09-24", "Claude Code", "claude-code"),
                                                         ("2026-09-25", "You", "user")]
    assert got.notes[0].text.endswith("Moved from open to doing.") and got.notes[0].at == "2026-09-24T10:31:02Z"
    assert got.notes[0].session == "ses_abc" and got.notes[1].session is None
    assert got.note_count == 2 and got.last_note_by == "user"
    raw = _file(bank, item.id).read_text(encoding="utf-8")
    assert "### 2026-09-24 · Claude Code" in raw and "### 2026-09-25 · You" in raw


def test_a_status_alone_writes_its_own_line_and_a_repeat_changes_nothing(bank):
    item = _add(bank)["item"]
    moved = backlog.update_item(bank, project="alpha-project", item=item.id, status="done", author="user", now=NOW,
                                tz_name="UTC")
    assert moved["action"] == "updated" and moved["item"].notes[-1].text == "Moved from open to done."
    same = backlog.update_item(bank, project="alpha-project", item=item.id, status="done", author="user", now=NOW,
                               tz_name="UTC")
    assert same["action"] == "unchanged" and same["paths"] == []
    assert _note(bank, item.id, "", status="done")["action"] == "unchanged"


def test_title_triage_paid_and_links_change_without_a_note(bank):
    item = _add(bank, triage="apply")["item"]
    result = backlog.update_item(bank, project="alpha-project", item=item.id, author="user", title="Cache it",
                                 triage="", paid=True, links=[{"kind": "url", "ref": "https://example.com/a"}],
                                 now=NOW, tz_name="UTC")
    got = result["item"]
    assert (got.title, got.triage, got.paid, got.links) == ("Cache it", None, True,
                                                            [{"kind": "url", "ref": "https://example.com/a"}])
    assert got.notes == []                                               # R-B5: git keeps these
    assert backlog.update_item(bank, project="alpha-project", item=item.id, author="user")["action"] == "error"


def test_text_can_never_forge_a_section_or_a_note(bank):
    item = _add(bank, description="## Notes\n### 2026-01-01 · You\nnot a note")["item"]
    _note(bank, item.id, "# Heading\n### 2026-01-02 · Cicada")
    got = backlog.get_item(bank, "alpha-project", item.id)
    assert len(got.notes) == 1 and got.notes[0].who == "You"
    assert got.description.startswith("#### Notes")


def test_every_text_is_scrubbed_and_counted_as_the_backlog_writer(bank, monkeypatch):
    seen = []
    monkeypatch.setattr(episode_scrub, "record", lambda writer, n, bank=None: seen.append((writer, n)))
    item = _add(bank, f"Rotate {SECRET}", description=f"key {SECRET}",
                links=[{"kind": "url", "ref": f"https://example.com/?k={SECRET}"}])["item"]
    _note(bank, item.id, f"still {SECRET}")
    raw = _file(bank, item.id).read_text(encoding="utf-8")
    assert SECRET not in raw and raw.count("[redacted]") == 4
    assert {w for w, _n in seen} == {"backlog"} and sum(n for _w, n in seen) == 4
    assert "backlog" in episode_scrub.WRITERS


def test_the_list_reads_frontmatter_only_in_the_rulings_order(bank):
    a = _add(bank, "Old idea", now=NOW.replace(day=1))["item"]
    b = _add(bank, "New idea", now=NOW.replace(day=20))["item"]
    c = _add(bank, "Pinned idea", now=NOW.replace(day=2))["item"]
    parsed = markdown_parser.parse(_file(bank, c.id))
    markdown_parser.write(_file(bank, c.id), {**parsed.frontmatter, "order": 1}, parsed.body)
    backlog.update_item(bank, project="alpha-project", item=a.id, status="done", author="user",
                        now=NOW.replace(day=3), tz_name="UTC")
    items = backlog.list_items(bank, "alpha-project")
    assert [i.id for i in items] == [c.id, b.id, a.id]
    assert backlog.counts(items) == {"open": 2, "doing": 0, "done": 1, "dropped": 0}
    assert backlog.open_counts(bank) == {"alpha-project": 2}
    assert items[2].note_count == 1 and items[2].last_note_by == "user"


def test_an_item_is_named_bare_or_by_its_project_and_never_guessed(bank):
    _entity(bank, "delta-project", type="project", name="Alpha Pilot")   # also "AP"
    one = _add(bank, "In alpha")["item"]
    two = _add(bank, "In delta", project="delta-project")["item"]
    assert one.id == two.id == "AP1"
    assert backlog.resolve_item(bank, "alpha-project/ap1") == ("alpha-project", "AP1")
    assert backlog.resolve_item(bank, "AP1", "delta-project") == ("delta-project", "AP1")
    ambiguous = backlog.resolve_item(bank, "AP1")
    assert ambiguous["action"] == "error" and "alpha-project/AP1" in ambiguous["error"]
    assert backlog.resolve_item(bank, "ZZ9")["action"] == "not_found"


def test_a_hand_written_note_reads_by_its_heading(bank):
    item = _add(bank)["item"]
    path = _file(bank, item.id)
    path.write_text(path.read_text(encoding="utf-8").rstrip() + "\n\n### 2026-09-26 · You\n\nAdded in Obsidian.\n",
                    encoding="utf-8")
    got = backlog.get_item(bank, "alpha-project", item.id)
    assert [(n.who, n.text, n.by, n.at) for n in got.notes] == [("You", "Added in Obsidian.", None, None)]
    assert backlog.author_of(got.notes[0]) == "user"


def test_days_are_the_writers_and_the_instant_is_utc(bank):
    item = _add(bank, now=datetime(2026, 9, 24, 20, 30, tzinfo=timezone.utc), tz_name="Asia/Tokyo")["item"]
    note = _note(bank, item.id, "x", now=datetime(2026, 9, 24, 20, 30, 9, 999, tzinfo=timezone.utc),
                 tz_name="Asia/Tokyo")["item"].notes[-1]
    assert item.created == "2026-09-25" and note.day == "2026-09-25" and note.at == "2026-09-24T20:30:09Z"
    assert backlog.local_day(note.at, "America/Los_Angeles") == "2026-09-24"


def test_an_unreadable_item_is_skipped_never_raised(bank):
    _add(bank)
    _file(bank, "AP9").write_text("---\n: [\n---\nbody", encoding="utf-8")
    assert [i.id for i in backlog.list_items(bank, "alpha-project")] == ["AP1"]


def test_the_backlog_component_moves_on_a_write(bank):
    before = sync_service.components(bank)["backlog"]
    _add(bank)
    assert sync_service.components(bank)["backlog"] != before
```

Run: `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_backlog_store.py -q -p no:cacheprovider` → the
module does not exist (`ImportError` at collection). That is the red.

- [ ] **Step 2: Implement.** Create `api/services/backlog.py`:

```python
"""G150 — a project's backlog is memory: one markdown file per item, and this
module is the ONE reader and writer of them.

Before G150, "put it in the backlog" meant an agent edited a markdown table in
some repository (the owner, 2026-09-24: "that backlog itself i believe should
go in cicada project memory … with the brief task and an appended
notes/description"). The table was invisible to Cicada, to every other agent
and to the person's own app. Now each item lives in the bank beside the
project it belongs to — `backlog/<project-id>/<item-id>.md` — with
frontmatter for what a list needs, a `## Description` for the reasoning, and
`## Notes`, an append-only log signed by whoever wrote each entry (R-B1).

Every path goes through here — REST (`routers/backlog.py`), MCP
(`mcp_tools.backlog` and its two writers, stdio and remote), the importer
(`backlog_import.py`) and the demo generator — so the id rule, the scrub, the
append-only notes and the status alphabet cannot drift between writers (the
`progress.py` precedent, G141 §5.1). Callers pass the ACTIVE bank's path (the
split-brain rule) and commit the memory-relative `paths` a write returns
themselves, each under its own author and trigger (R-B7). Nothing here
commits, and nothing here raises on a normal input: a refusal is a dict whose
`action` is `error`, `not_found`, `duplicate` or `exists`, with one `error`
sentence, and it wrote nothing (the `agentic_write` contract).

The rails, each a G150 ruling:

* **Never an entity page** (R-B1, R-B3). This module never writes
  `entities/`: no `last_referenced` bump, no prefix, no claim.
* **Ids are addresses** (R-B2): `<PREFIX><n>`, max+1 per prefix (G114's
  lesson), claimed by an exclusive create so the backend and every stdio MCP
  process can mint at once.
* **Notes are append-only** (R-B4, R-B5): git history is a note's edit log,
  and a status move is itself a signed note.
* **Scrubbed** (R-B10): a description is where a pasted key lands.
"""
from __future__ import annotations

import fcntl
import os
import re
import unicodedata
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml
from loguru import logger

from api.services import bank_index, markdown_parser

BACKLOG_DIR = "backlog"
STATUSES = ("open", "doing", "done", "dropped")
OPEN_STATUSES = frozenset({"open", "doing"})
TRIAGES = ("apply", "research", "decide")
LINK_KINDS = ("pr", "commit", "url", "doc", "entity")
USER = "user"
CICADA = "cicada"
AGENT = "agent"
TITLE_CHARS = 200
DESCRIPTION_CHARS = 20_000
NOTE_CHARS = 8_000
LINK_CHARS = 500
MAX_LINKS = 20
MINT_TRIES = 50
# Bumped when a reader's wire changes shape for the same files; the REST ETags
# fold it beside `git_service.AUTHOR_SHAPE` (R-B18).
BACKLOG_SHAPE = "g150-1"
ID_RE = re.compile(r"^([A-Z]{1,6})(\d{1,6})([a-z]?)$")
_LOOSE_ID = re.compile(r"^([A-Za-z]{1,6})(\d{1,6})([A-Za-z]?)$")
_PREFIX_RE = re.compile(r"^[A-Z]{1,6}$")
_NOTE_HEAD = re.compile(r"^### (\d{4}-\d{2}-\d{2}) · (.+?)[ \t]*$", re.M)
_HEADING = re.compile(r"(?m)^#{1,3}(?=[ \t])")
DESCRIPTION_HEAD = "## Description"
NOTES_HEAD = "## Notes"
NO_DESCRIPTION = "_No description yet._"


@dataclass
class Note:
    """One `### <day> · <who>` entry (R-B4). `by`, `at` and `session` come
    from the frontmatter sidecar; a note appended by hand has none of them."""
    day: str
    who: str
    text: str
    by: str | None = None
    at: str | None = None
    session: str | None = None


@dataclass
class Item:
    id: str
    project: str
    title: str
    status: str = "open"
    triage: str | None = None
    paid: bool = False
    created: str = ""
    updated: str = ""
    added_by: str = USER
    session: str | None = None
    links: list[dict] = field(default_factory=list)
    order: int | None = None
    description: str = ""
    notes: list[Note] = field(default_factory=list)
    # From the sidecar when only the frontmatter was read (a list row).
    note_count: int = 0
    last_note_at: str | None = None
    last_note_by: str | None = None

    @property
    def path(self) -> str:
        """Memory-relative — what a caller commits and a commit line names."""
        return f"{BACKLOG_DIR}/{self.project}/{self.id}.md"


def _error(message: str, **extra) -> dict:
    return {"action": "error", "error": message, **extra}


# --------------------------------------------------------------------------- #
# who and when
# --------------------------------------------------------------------------- #


def author_id(author: str | None) -> str:
    value = (author or "").strip()
    return value or AGENT


def who_label(by: str | None) -> str:
    """A note heading's words for an author id (R-B4): "You", "Cicada", a
    harness's product name through the one harness → name map, else "An
    agent" — `fact_sources.voiced_hint`'s rule, so an agent is named the same
    way on a conflict card and in a backlog note."""
    value = (by or "").strip()
    if value == USER:
        return "You"
    if value == CICADA:
        return "Cicada"
    from api.services.source_overview import HARNESS_LABELS, UNKNOWN

    label = HARNESS_LABELS.get(value) if value != UNKNOWN else None
    return label or "An agent"


def author_of(note: Note) -> str:
    """The author id behind a note: the sidecar's, else read back from the
    heading's words — a hand-written "You" is the person (R-B4)."""
    if note.by:
        return note.by
    if note.who == "You":
        return USER
    if note.who == "Cicada":
        return CICADA
    from api.services.source_overview import HARNESS_LABELS

    return next((k for k, v in HARNESS_LABELS.items() if v == note.who), AGENT)


def _clock(now: datetime | None, tz_name: str | None) -> tuple[str, str]:
    """`(day, at)`: the writer's day in the machine zone (R-B11 — the person's
    calendar, like every G141 date) and the UTC instant to the second,
    `Z`-suffixed — round 4's C2 `recorded_ts` shape, so a note can be joined
    to the turn it was written in at read (R-B6)."""
    from api.services import handshake, when

    tz = when.zone(tz_name or handshake.local_timezone())
    instant = (now or datetime.now(tz)).replace(microsecond=0)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=tz)
    return instant.astimezone(tz).date().isoformat(), when.utc_z(instant)


def local_day(at: str | None, tz_name: str | None) -> str | None:
    """The day an instant fell on in `tz_name` — the wire's `lastNoteDay`."""
    from api.services import when

    instant = when.parse_instant(at) if at else None
    return instant.astimezone(when.zone(tz_name)).date().isoformat() if instant else None


def status_line(old: str, new: str) -> str:
    return f"Moved from {old} to {new}."


# --------------------------------------------------------------------------- #
# projects and ids
# --------------------------------------------------------------------------- #


def project_page(memory_path: Path, project: str) -> tuple[str, dict] | dict:
    """`(stem, frontmatter)` for a live project page, or a refusal (R-B14).

    Resolves ids, names and aliases like every project reader; re-reads the
    real stem on a case-insensitive filesystem (`progress._page`'s reason). A
    miss, a non-project and a dropped page are refused, and nothing here ever
    creates a page."""
    from api.services.id_utils import resolve_entity_file

    ref = (project or "").strip()
    page = resolve_entity_file(Path(memory_path), ref) if ref else None
    if page is None or not page.is_file():
        return {"action": "not_found", "error": f"no project {ref!r}; nothing was written"}
    page = next((f for f in page.parent.glob("*.md") if f.name.lower() == page.name.lower()), page)
    try:
        fm = markdown_parser.parse(page).frontmatter or {}
    except Exception:  # noqa: BLE001 — an unreadable page is a refusal, never a raise
        return _error(f"{page.stem} can't be read; nothing was written")
    kind = str(fm.get("type") or "page")
    if kind != "project":
        return {"action": "not_found", "error": f"{page.stem} is a {kind}, not a project; nothing was written"}
    if str(fm.get("status") or "active") == "dropped":
        return {"action": "not_found", "error": f"{page.stem} was dropped from memory; nothing was written"}
    return page.stem, fm


def initials(name: str) -> str:
    """R-B2's default prefix: the first letters of up to four words, or the
    first three letters of a one-word name ("Orchard" → ORC, "Rover Arm
    Project" → RAP). ASCII letters only after NFKD folding, so an id is
    typeable anywhere; "T" (task) when nothing is left."""
    folded = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode("ascii")
    words = [w for w in re.split(r"[^A-Za-z0-9]+", folded) if w and w[0].isalpha()]
    if not words:
        return "T"
    if len(words) == 1:
        return re.sub(r"[^A-Z]", "", words[0].upper())[:3] or "T"
    return "".join(w[0].upper() for w in words[:4])


def _folder(memory_path: Path, stem: str) -> Path:
    return Path(memory_path) / BACKLOG_DIR / stem


def _item_files(memory_path: Path, stem: str) -> list[Path]:
    folder = _folder(memory_path, stem)
    return sorted(p for p in folder.glob("*.md") if p.is_file()) if folder.is_dir() else []


def prefix_for(memory_path: Path, stem: str, fm: dict | None) -> str:
    """R-B2: the page's `backlog_prefix:`, else the prefix most of the
    project's items already share (ties alphabetical) — so an imported G-row
    backlog continues at G<max+1> without this module ever writing an entity
    page (R-B3) — else the name's initials."""
    stated = str((fm or {}).get("backlog_prefix") or "").strip().upper()
    if _PREFIX_RE.match(stated):
        return stated
    shared = Counter(m.group(1) for m in (ID_RE.match(p.stem) for p in _item_files(memory_path, stem)) if m)
    if shared:
        top = max(shared.values())
        return sorted(k for k, v in shared.items() if v == top)[0]
    return initials(str((fm or {}).get("name") or stem.replace("-", " ")))


def next_number(memory_path: Path, stem: str, prefix: str) -> int:
    """1 + the highest number already filed under `prefix` — never a count
    (G114: a count collides after any gap)."""
    top = 0
    for p in _item_files(memory_path, stem):
        m = ID_RE.match(p.stem)
        if m and m.group(1) == prefix:
            top = max(top, int(m.group(2)))
    return top + 1


def normalize_id(raw: str | None) -> str | None:
    """`rap3` → `RAP3`, `G074a` → `G74a`; anything else (a path, a word) → None."""
    m = _LOOSE_ID.match((raw or "").strip())
    return f"{m.group(1).upper()}{int(m.group(2))}{m.group(3).lower()}" if m else None


def item_path(memory_path: Path, stem: str, item: str) -> Path | None:
    iid = normalize_id(item)
    if iid is None:
        return None
    exact = _folder(memory_path, stem) / f"{iid}.md"
    if exact.is_file():
        return exact
    return next((p for p in _item_files(memory_path, stem) if p.stem.upper() == iid.upper()), None)


def resolve_item(memory_path: Path, ref: str, project: str | None = None) -> tuple[str, str] | dict:
    """An item named the way an agent names it (R-B13): `RAP3`,
    `rover-arm-project/RAP3`, or `RAP3` with `project`. A bare id two
    projects both hold is refused with both addresses — never guessed."""
    raw = (ref or "").strip()
    if "/" in raw:
        project, raw = raw.rsplit("/", 1)
    iid = normalize_id(raw)
    if iid is None:
        return _error(f"{ref!r} isn't an item id like RAP3; nothing was read")
    if project:
        got = project_page(memory_path, project)
        if isinstance(got, dict):
            return got
        stem = got[0]
        if item_path(memory_path, stem, iid) is None:
            return {"action": "not_found", "error": f"no {iid} on {stem}'s backlog"}
        return stem, iid
    root = Path(memory_path) / BACKLOG_DIR
    holders = sorted(d.name for d in root.iterdir()
                     if d.is_dir() and item_path(memory_path, d.name, iid) is not None) if root.is_dir() else []
    if not holders:
        return {"action": "not_found", "error": f"no backlog item {iid}"}
    if len(holders) > 1:
        both = ", ".join(f"{h}/{iid}" for h in holders)
        return _error(f"{iid} is on more than one backlog ({both}) — name it as <project>/{iid}")
    return holders[0], iid


# --------------------------------------------------------------------------- #
# text
# --------------------------------------------------------------------------- #


def _scrub(text: str | None, bank: str) -> str:
    """R-B10: every writer scrubs, and the count is ledgered as `backlog`."""
    from api.services import episode_scrub

    cleaned, n = episode_scrub.scrub(text or "")
    episode_scrub.record("backlog", n, bank=bank)
    return cleaned


def _block(text: str, cap: int) -> str:
    """Markdown made safe for the item's own structure (R-B4): trimmed,
    capped, and every level 1–3 heading demoted to `####`, so a pasted
    "## Notes" or "### 2026-09-01 · You" can never start a section or forge a
    note. Nothing else about the markdown changes."""
    text = (text or "").replace("\r\n", "\n").strip()
    return _HEADING.sub("####", text)[:cap].rstrip()


def _title(text: str) -> str:
    return " ".join((text or "").split())[:TITLE_CHARS]


def fold_title(text: str) -> str:
    """R-B9's comparison: lower case, single spaces — exact, never fuzzy."""
    return " ".join((text or "").lower().split())


def validate_links(raw) -> list[dict] | str:
    """`[{kind, ref}]` for a write, or one sentence saying what is wrong — a
    writer names a bad kind rather than having it dropped silently."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        return "links is a list of {kind, ref}; nothing was written"
    out: list[dict] = []
    for entry in raw:
        kind = str(entry.get("kind") or "").strip().lower() if isinstance(entry, dict) else ""
        ref = " ".join(str(entry.get("ref") or "").split())[:LINK_CHARS] if isinstance(entry, dict) else ""
        if kind not in LINK_KINDS or not ref:
            return f"a link is {{kind, ref}} with kind one of {', '.join(LINK_KINDS)}; nothing was written"
        if {"kind": kind, "ref": ref} not in out:
            out.append({"kind": kind, "ref": ref})
    return out[:MAX_LINKS]


def _clean_links(raw) -> list[dict]:
    """The reader's half: a hand-edited bad entry is skipped, never raised."""
    out: list[dict] = []
    for entry in raw if isinstance(raw, list) else []:
        if isinstance(entry, dict):
            kind = str(entry.get("kind") or "").strip().lower()
            ref = str(entry.get("ref") or "").strip()
            if kind in LINK_KINDS and ref and {"kind": kind, "ref": ref} not in out:
                out.append({"kind": kind, "ref": ref})
    return out[:MAX_LINKS]


def _find_heading(text: str, heading: str) -> int:
    m = re.search(rf"(?m)^{re.escape(heading)}[ \t]*$", text)
    return m.start() if m else -1


def parse_body(body: str) -> tuple[str, list[tuple[str, str, str]]]:
    """`(description, [(day, who, text)])` from an item's body. Tolerant: a
    body with no `## Description` is all description, and text under
    `## Notes` before its first note is kept as the description's tail —
    never dropped."""
    text = body or ""
    at = _find_heading(text, NOTES_HEAD)
    head, tail = (text[:at], text[at + len(NOTES_HEAD):]) if at >= 0 else (text, "")
    d = _find_heading(head, DESCRIPTION_HEAD)
    description = (head[d + len(DESCRIPTION_HEAD):] if d >= 0 else head).strip()
    if description == NO_DESCRIPTION:
        description = ""
    heads = list(_NOTE_HEAD.finditer(tail))
    stray = (tail[: heads[0].start()] if heads else tail).strip()
    if stray:
        description = f"{description}\n\n{stray}".strip()
    notes = []
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(tail)
        notes.append((m.group(1), m.group(2).strip(), tail[m.end():end].strip()))
    return description, notes


def render_body(description: str, notes: list[Note]) -> str:
    parts = [DESCRIPTION_HEAD, "", description.strip() or NO_DESCRIPTION, "", NOTES_HEAD]
    for n in notes:
        parts += ["", f"### {n.day} · {n.who}", "", n.text.strip()]
    return "\n".join(parts)


def _sidecar(fm: dict | None) -> list[dict]:
    """The `notes:` sidecar, positions kept (a malformed entry is `{}`)."""
    raw = (fm or {}).get("notes")
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for entry in raw:
        entry = entry if isinstance(entry, dict) else {}
        out.append({k: str(entry[k]) for k in ("by", "at", "session") if entry.get(k) not in (None, "")})
    return out


def _render(item: Item) -> str:
    """R-B1's key order; empty keys omitted; the sidecar last, like `turns`."""
    fm: dict = {"id": item.id, "title": item.title, "project": item.project, "status": item.status}
    if item.triage:
        fm["triage"] = item.triage
    if item.paid:
        fm["paid"] = True
    fm["created"] = item.created
    fm["updated"] = item.updated
    fm["added_by"] = item.added_by
    if item.session:
        fm["session"] = item.session
    if item.links:
        fm["links"] = item.links
    if item.order is not None:
        fm["order"] = item.order
    if item.notes:
        fm["notes"] = [{k: v for k, v in (("at", n.at), ("by", n.by), ("session", n.session)) if v}
                       for n in item.notes]
    dumped = yaml.dump(fm, default_flow_style=False, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{dumped}\n---\n\n{render_body(item.description, item.notes)}\n"


# --------------------------------------------------------------------------- #
# reading
# --------------------------------------------------------------------------- #


def _from_fm(fm: dict, path: Path, stem: str) -> Item:
    """A list row from frontmatter alone (R-B2: the file name is the id)."""
    side = _sidecar(fm)
    last = side[-1] if side else {}
    status = str(fm.get("status") or "open").strip().lower()
    triage = str(fm.get("triage") or "").strip().lower() or None
    order = fm.get("order")
    return Item(
        id=path.stem, project=stem, title=str(fm.get("title") or path.stem),
        status=status if status in STATUSES else "open",
        triage=triage if triage in TRIAGES else None, paid=fm.get("paid") is True,
        created=str(fm.get("created") or "")[:10], updated=str(fm.get("updated") or fm.get("created") or "")[:10],
        added_by=str(fm.get("added_by") or USER), session=str(fm.get("session") or "") or None,
        links=_clean_links(fm.get("links")),
        order=order if isinstance(order, int) and not isinstance(order, bool) else None,
        note_count=len(side), last_note_at=last.get("at"), last_note_by=last.get("by"))


def _read(path: Path, stem: str) -> Item | None:
    try:
        parsed = markdown_parser.parse(path)
    except Exception as exc:  # noqa: BLE001 — one unreadable file never fails a caller
        logger.warning(f"backlog: skipping unreadable {path.name}: {type(exc).__name__}")
        return None
    item = _from_fm(parsed.frontmatter or {}, path, stem)
    description, raw = parse_body(parsed.body)
    side = _sidecar(parsed.frontmatter)
    if len(side) > len(raw):
        side = []   # R-B4: a note deleted by hand — positions no longer mean anything
    item.description = description
    item.notes = [Note(day=d, who=w, text=t, **(side[i] if i < len(side) else {}))
                  for i, (d, w, t) in enumerate(raw)]
    item.note_count = len(item.notes)
    item.last_note_at = item.notes[-1].at if item.notes else None
    item.last_note_by = author_of(item.notes[-1]) if item.notes else None
    return item


def sort_items(items: list[Item]) -> list[Item]:
    """R-B19's order: a hand-set `order` first (ascending), then the most
    recently touched, then the highest number — stable sorts, last key first."""
    def number(i: Item) -> int:
        m = ID_RE.match(i.id)
        return int(m.group(2)) if m else 0

    out = sorted(items, key=number, reverse=True)
    out.sort(key=lambda i: (i.updated, i.last_note_at or ""), reverse=True)
    out.sort(key=lambda i: (i.order is None, i.order if i.order is not None else 0))
    return out


def list_items(memory_path: Path, stem: str) -> list[Item]:
    """Every item of a project from frontmatter alone — `bank_index`'s cache,
    no body parse — in R-B19's order. A file whose name is not an id, or
    whose frontmatter will not parse, is skipped."""
    files = bank_index.files(Path(memory_path), f"{BACKLOG_DIR}/{stem}")
    return sort_items([_from_fm(f.frontmatter or {}, f.path, stem) for f in files if ID_RE.match(f.path.stem)])


def get_item(memory_path: Path, stem: str, item: str) -> Item | None:
    path = item_path(memory_path, stem, item)
    return _read(path, stem) if path is not None else None


def counts(items: list[Item]) -> dict[str, int]:
    out = {s: 0 for s in STATUSES}
    for i in items:
        out[i.status] = out.get(i.status, 0) + 1
    return out


def open_counts(memory_path: Path) -> dict[str, int]:
    """`{project: n}` of items `open` or `doing` — `_state.md`'s
    `backlog_open` (R-B16); a project with none is absent."""
    root = Path(memory_path) / BACKLOG_DIR
    out: dict[str, int] = {}
    if root.is_dir():
        for folder in sorted(p for p in root.iterdir() if p.is_dir()):
            n = sum(1 for i in list_items(memory_path, folder.name) if i.status in OPEN_STATUSES)
            if n:
                out[folder.name] = n
    return out


def stamp(memory_path: Path) -> str:
    """`sync_service`'s `backlog` component (R-B16): folders, item files and
    the newest mtime, from a stat walk two levels deep — no parse, so
    `GET /sync/version` stays well under 10 ms."""
    root = Path(memory_path) / BACKLOG_DIR
    dirs = files = newest = 0
    try:
        with os.scandir(root) as outer:
            for d in outer:
                if not d.is_dir():
                    continue
                dirs += 1
                with os.scandir(d.path) as inner:
                    for e in inner:
                        if e.is_file() and e.name.endswith(".md"):
                            files += 1
                            newest = max(newest, e.stat().st_mtime_ns)
    except FileNotFoundError:
        pass
    return f"{dirs}:{files}:{newest}"


# --------------------------------------------------------------------------- #
# writing
# --------------------------------------------------------------------------- #


def _claim(path: Path, text: str) -> bool:
    """Create `path` only if nobody has (`O_EXCL`) — R-B2's cross-process
    half: the backend and every stdio MCP process mint in the same folder,
    and check-then-write would let two of them take one number."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    return True


@contextmanager
def _locked(path: Path):
    """An exclusive advisory lock on the item file for one read-modify-write
    — two processes appending notes to one item never lose one."""
    fd = os.open(path, os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield fd
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _write_fd(fd: int, text: str) -> None:
    data = memoryview(text.encode("utf-8"))
    os.lseek(fd, 0, os.SEEK_SET)
    os.ftruncate(fd, 0)
    while data:
        data = data[os.write(fd, data):]


def _session(session: str | None) -> str | None:
    return (session or "").strip() or None


def add_item(memory_path: Path, *, project: str, title: str, description: str = "", author: str,
             triage: str | None = None, paid: bool = False, links=None, session: str | None = None,
             status: str = "open", item_id: str | None = None, created: str | None = None,
             first_note: str | None = None, now: datetime | None = None, tz_name: str | None = None) -> dict:
    """File one item on a project's backlog (R-B1).

    `item_id`, `status`, `created` and `first_note` are the importer's
    (R-B15): an import keeps the file's id and state and says where it came
    from; every other writer mints the next number and opens it. Returns
    `{action: "added", item, paths}`, or a refusal that wrote nothing:
    `not_found` (no such project), `duplicate` (an open item already holds the
    title — R-B9 — with `item_id` and `project`), `exists` (the importer's id is
    taken, with `item_id`) or `error`."""
    try:
        memory_path = Path(memory_path)
        got = project_page(memory_path, project)
        if isinstance(got, dict):
            return got
        stem, fm = got
        bank = memory_path.name
        if status not in STATUSES:
            return _error(f"a status is one of {', '.join(STATUSES)}; nothing was written")
        triage = (triage or "").strip().lower() or None
        if triage is not None and triage not in TRIAGES:
            return _error(f"triage is one of {', '.join(TRIAGES)}; nothing was written")
        links_ok = validate_links(links)
        if isinstance(links_ok, str):
            return _error(links_ok)
        clean_title = _title(_scrub(title, bank))
        if not clean_title:
            return _error("give the item a title — the brief task, in one line; nothing was written")
        if item_id is None:
            folded = fold_title(clean_title)
            clash = next((i for i in list_items(memory_path, stem)
                          if i.status in OPEN_STATUSES and fold_title(i.title) == folded), None)
            if clash is not None:
                return {"action": "duplicate", "item_id": clash.id, "project": stem,
                        "error": f"{clash.id} already holds this — add what you found to it as a note"}
        day, at = _clock(now, tz_name)
        by = author_id(author)
        item = Item(id="", project=stem, title=clean_title, status=status, triage=triage, paid=bool(paid),
                    created=(created or day)[:10], updated=day, added_by=by, session=_session(session),
                    links=[{**link, "ref": _scrub(link["ref"], bank)} for link in links_ok],
                    description=_block(_scrub(description, bank), DESCRIPTION_CHARS))
        if first_note:
            item.notes = [Note(day=day, who=who_label(by), text=_block(_scrub(first_note, bank), NOTE_CHARS),
                               by=by, at=at, session=item.session)]
        folder = _folder(memory_path, stem)
        if item_id is not None:
            iid = normalize_id(item_id)
            if iid is None:
                return _error(f"{item_id!r} isn't an item id; nothing was written")
            item.id = iid
            if not _claim(folder / f"{iid}.md", _render(item)):
                return {"action": "exists", "item_id": iid, "project": stem,
                        "error": f"{iid} is already on this backlog"}
        else:
            prefix = prefix_for(memory_path, stem, fm)
            n = next_number(memory_path, stem, prefix)
            for _ in range(MINT_TRIES):
                item.id = f"{prefix}{n}"
                if _claim(folder / f"{item.id}.md", _render(item)):
                    break
                n += 1
            else:
                return _error("couldn't take a new id; nothing was written")
        item.note_count = len(item.notes)
        item.last_note_at = item.notes[-1].at if item.notes else None
        item.last_note_by = by if item.notes else None
        return {"action": "added", "item": item, "paths": [item.path]}
    except Exception as exc:  # noqa: BLE001 — never raise on a normal input
        logger.warning(f"backlog.add_item failed: {type(exc).__name__}: {exc}")
        return _error(f"{type(exc).__name__}: {exc}")


def _update(memory_path: Path, project: str, item: str, change) -> dict:
    """One locked read-modify-write of an existing item. `change(item)`
    mutates it and returns None, or returns a reply that writes nothing."""
    got = project_page(memory_path, project)
    if isinstance(got, dict):
        return got
    stem = got[0]
    path = item_path(memory_path, stem, item)
    if path is None:
        return {"action": "not_found",
                "error": f"no {normalize_id(item) or item!r} on {stem}'s backlog; nothing was written"}
    with _locked(path) as fd:
        current = _read(path, stem)
        if current is None:
            return _error(f"{path.stem} can't be read; nothing was written")
        verdict = change(current)
        if isinstance(verdict, dict):
            return verdict
        current.note_count = len(current.notes)
        current.last_note_at = current.notes[-1].at if current.notes else None
        current.last_note_by = author_of(current.notes[-1]) if current.notes else None
        _write_fd(fd, _render(current))
    return {"action": "updated", "item": current, "paths": [current.path]}


def add_note(memory_path: Path, *, project: str, item: str, note: str, author: str, status: str | None = None,
             session: str | None = None, now: datetime | None = None, tz_name: str | None = None) -> dict:
    """Append one signed note (R-B4) — and, with `status`, move the item in
    the same write, the move said as the note's last line (R-B5). A note that
    says nothing and moves nothing is `unchanged`, and so is a move to the
    state the item is already in with no words."""
    try:
        memory_path = Path(memory_path)
        if status is not None and status not in STATUSES:
            return _error(f"a status is one of {', '.join(STATUSES)}; nothing was written")
        text = _block(_scrub(note, memory_path.name), NOTE_CHARS)
        if not text and status is None:
            return _error("say what you found; nothing was written")
        by = author_id(author)
        day, at = _clock(now, tz_name)

        def change(it: Item):
            body = text
            if status is not None and status != it.status:
                body = f"{body}\n\n{status_line(it.status, status)}".strip()
                it.status = status
            if not body:
                return {"action": "unchanged", "item": it, "paths": []}
            it.notes.append(Note(day=day, who=who_label(by), text=body, by=by, at=at, session=_session(session)))
            it.updated = day
            return None

        return _update(memory_path, project, item, change)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"backlog.add_note failed: {type(exc).__name__}: {exc}")
        return _error(f"{type(exc).__name__}: {exc}")


def update_item(memory_path: Path, *, project: str, item: str, author: str, title: str | None = None,
                status: str | None = None, triage: str | None = None, paid: bool | None = None, links=None,
                session: str | None = None, now: datetime | None = None, tz_name: str | None = None) -> dict:
    """The person's edits (and a script's): a title, a triage (`""` clears
    it), the 💸 flag, the links, a status. A status move is written as a
    signed note — the one change the card's notes must show (R-B5); the
    others live in git history."""
    try:
        memory_path = Path(memory_path)
        bank = memory_path.name
        if all(v is None for v in (title, status, triage, paid, links)):
            return _error("say what to change: a title, a status, a triage, the paid flag or the links")
        if status is not None and status not in STATUSES:
            return _error(f"a status is one of {', '.join(STATUSES)}; nothing was written")
        new_triage = None if triage is None else (triage.strip().lower() or "")
        if new_triage and new_triage not in TRIAGES:
            return _error(f"triage is one of {', '.join(TRIAGES)}; nothing was written")
        new_title = None if title is None else _title(_scrub(title, bank))
        if title is not None and not new_title:
            return _error("a title can't be empty; nothing was written")
        links_ok = None if links is None else validate_links(links)
        if isinstance(links_ok, str):
            return _error(links_ok)
        by = author_id(author)
        day, at = _clock(now, tz_name)

        def change(it: Item):
            before = (it.title, it.status, it.triage, it.paid, it.links)
            if new_title is not None:
                it.title = new_title
            if new_triage is not None:
                it.triage = new_triage or None
            if paid is not None:
                it.paid = bool(paid)
            if links_ok is not None:
                it.links = [{**link, "ref": _scrub(link["ref"], bank)} for link in links_ok]
            if status is not None and status != it.status:
                it.notes.append(Note(day=day, who=who_label(by), text=status_line(it.status, status), by=by,
                                     at=at, session=_session(session)))
                it.status = status
            if (it.title, it.status, it.triage, it.paid, it.links) == before:
                return {"action": "unchanged", "item": it, "paths": []}
            it.updated = day
            return None

        return _update(memory_path, project, item, change)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"backlog.update_item failed: {type(exc).__name__}: {exc}")
        return _error(f"{type(exc).__name__}: {exc}")


def commit_message(paths: list[str], *, action: str, subject: str, trigger: str, day: str, author: str = USER,
                   session: str | None = None) -> str:
    """The house commit for a backlog write (R-B7): one manifest line per
    file, the author trailer, the conversation when there is one — what
    `parse_cycle_body` and `cicada_timeline` already read."""
    from api.services import git_service

    return git_service.build_commit_message(
        f"{subject} {day}", [f"{p}: {action} (source: n/a, trigger: {trigger})" for p in dict.fromkeys(paths)],
        authors=[author], sessions=[session] if session else None)
```

- [ ] **Step 3: The writer word and the component.** In `api/services/episode_scrub.py:36-39` add `"backlog"` to
  `WRITERS` (after `"demo"`), with a one-line comment `# G150 R-B10: a backlog item's title, description and notes`.
  In `api/services/sync_service.py`, add `backlog` to the existing `from api.services import bank_index, logo_service,
  markdown_parser, telemetry` line (`:18`; `backlog` imports neither `sync_service` nor anything that does, so there is
  no cycle) and add one key to the dict `components()` returns, after `"episodes"`:

```python
        # G150 R-B16: every backlog item's stamp (a stat walk, no parse) — the
        # Projects page's backlog reads and `_state.md`'s `backlog_open` move
        # on it; nothing in `entities`/`episodes` notices a backlog write.
        "backlog": backlog.stamp(mp),
```

- [ ] **Step 4: Green.** `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_backlog_store.py
  api/tests/test_episode_writers_scrub.py api/tests/test_episode_scrub.py api/tests/test_sync.py -q -p
  no:cacheprovider` passes (`test_sync.py` is where `sync_service.components()` is tested). Then the full backend
  suite: `cd <worktree> && api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider` → 0 failures.

- [ ] **Step 5: Commit.**

```bash
cd <worktree> && git add api/services/backlog.py api/services/episode_scrub.py api/services/sync_service.py \
  api/tests/test_backlog_store.py && git commit -m "feat(backlog): one markdown file per item, one writer (G150 R-B1…R-B11)

A project's backlog lives in the bank at backlog/<project>/<id>.md: the brief
task as the title, the reasoning under ## Description, append-only signed notes
under ## Notes (a status move is itself a note). Ids are <PREFIX><n>, max+1
per prefix, claimed by an exclusive create; the writer never touches an entity
page, scrubs every text as writer 'backlog', and refuses a second open item
for the same idea. A 'backlog' sync component stamps the folder.

<attribution lines>"
```

---

### Task 2: The person's routes, the importer, and the demo's backlog (G150 R-B7, R-B8, R-B9, R-B15, R-B18, R-B26)

Six routes over Task 1's writer, the importer and its script, and five synthetic items on the demo's rover project —
with the demo's backlog wire generated into the fixture every Swift test in Tasks 4–6 reads. After this task the
backlog is usable over HTTP and the demo shows one; no agent tool and no UI yet.

**Files:**
- Modify: `api/models/schemas.py` — the ten backlog models, after `ProjectWriteResponse` (`:1247-1253`)
- Create: `api/routers/backlog.py`
- Modify: `api/main.py:13-45` (import) and `:209` (mount after `projects`)
- Create: `api/services/backlog_import.py`, `scripts/import-backlog.sh` (executable)
- Modify: `api/services/demo_bank.py` — `_write_scenario_backlog` and its call in `populate` (`:101-129`)
- Modify: `api/tests/_demo_scenario.py:22-49` — the `backlog` step flag
- Create: `api/tests/test_backlog_router.py`, `api/tests/test_backlog_import.py`, `api/tests/test_backlog_app_fixture.py`
- Create (generated): `app/CicadaApp/Tests/fixtures/backlog-demo.json`

**Interfaces:**
- Produces the wire (camelCase through `CamelModel`):
  - `GET /projects/{id}/backlog[?status=]` → `{project, projectName, prefix, counts: {open, doing, done, dropped},
    items: [BacklogItemSummary], tzName}`; `BacklogItemSummary` = `{id, project, title, status, triage?, paid,
    created, updated, addedBy, addedByKind, addedByLabel, noteCount, lastNoteDay?, lastNoteBy?, order?}`.
  - `GET /backlog/{project}/{item}` → `BacklogItemModel` = the summary + `{description, notes: [{day, text, by,
    byKind, byProvider?, byLabel, at?, session?, authorModel?, authorEffort?}], links: [{kind, ref}], session?, path}`.
  - `POST /projects/{id}/backlog` `{title, description?, triage?, paid?}`, `POST /backlog/{project}/{item}/notes`
    `{note, status?}`, `PATCH /backlog/{project}/{item}` `{title?, status?, triage?, paid?, links?}` → the item;
    404 / 409 (Sleep, or a duplicate: the sentence names the item) / 400.
  - `POST /projects/{id}/backlog/import` `{markdown, prefix?}` → `{created, skipped, failed}`.
- Produces `backlog_import.parse`, `status_of`, `import_markdown`, `import_file`, `IMPORT_TRIGGER`, `MAX_CHARS`;
  `routers/backlog._now` (the clock seam tests pin); `demo_bank._write_scenario_backlog`.
- Consumes Task 1's `backlog.*`.

- [ ] **Step 1: Failing tests.** Create `api/tests/test_backlog_router.py`:

```python
"""G150 — a project's backlog over HTTP (R-B7, R-B8, R-B9, R-B18).

Every write is the person's (`Cicada-Author: user`, `user/companion_app`), commits alone over the item's own
file, refuses while Sleep runs, and scrubs. Synthetic only (`_synthetic_bank`)."""
import subprocess
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from _synthetic_bank import _bank
from api import config, main
from api.routers import backlog as backlog_router
from api.services import bank_index, handshake, sleep_cycle

SECRET = "sk-" + "Z" * 24


@pytest.fixture
def client(tmp_path, monkeypatch):
    bank = _bank(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    monkeypatch.setattr(handshake, "local_timezone", lambda: "UTC")
    monkeypatch.setattr(backlog_router, "_now", lambda: datetime(2026, 9, 24, 18, tzinfo=UTC))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    yield TestClient(main.app), bank
    config.get_settings.cache_clear()


def _git(bank, *args):
    return subprocess.run(["git", *args], cwd=bank, capture_output=True, text=True, check=True).stdout


def _add(c, title="Cache the timeline", **body):
    return c.post("/projects/alpha-project/backlog", json={"title": title, **body})


def test_the_person_adds_an_item_and_it_commits_alone_as_theirs(client):
    c, bank = client
    r = _add(c, description=f"The key was {SECRET}", triage="apply")
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["id"], body["status"], body["triage"]) == ("AP1", "open", "apply")
    assert (body["addedBy"], body["addedByKind"], body["addedByLabel"]) == ("user", "user", "You")
    assert SECRET not in body["description"] and body["path"] == "backlog/alpha-project/AP1.md"
    log = _git(bank, "log", "-1", "--format=%B")
    assert log.startswith("Backlog update 2026-09-24") and "Cicada-Author: user" in log
    assert "backlog/alpha-project/AP1.md: created (source: n/a, trigger: user/companion_app)" in log
    assert _git(bank, "show", "--name-only", "--format=", "HEAD").split() == ["backlog/alpha-project/AP1.md"]


def test_the_list_is_etagged_counts_every_state_and_filters(client):
    c, _bank_dir = client
    _add(c, "One")
    _add(c, "Two")
    c.post("/backlog/alpha-project/AP1/notes", json={"note": "Started.", "status": "doing"})
    r = c.get("/projects/alpha-project/backlog")
    assert r.status_code == 200 and r.headers["etag"]
    body = r.json()
    assert (body["project"], body["projectName"], body["prefix"], body["tzName"]) == (
        "alpha-project", "Alpha Project", "AP", "UTC")
    assert body["counts"] == {"open": 1, "doing": 1, "done": 0, "dropped": 0}
    assert [i["id"] for i in body["items"]] == ["AP1", "AP2"]          # same day: the one with a note is newer
    assert body["items"][0]["lastNoteDay"] == "2026-09-24" and body["items"][0]["noteCount"] == 1
    again = c.get("/projects/alpha-project/backlog", headers={"If-None-Match": r.headers["etag"]})
    assert again.status_code == 304
    assert [i["id"] for i in c.get("/projects/alpha-project/backlog?status=doing").json()["items"]] == ["AP1"]
    assert c.get("/projects/alpha-project/backlog?status=someday").status_code == 400
    _add(c, "Three")
    assert c.get("/projects/alpha-project/backlog", headers={"If-None-Match": r.headers["etag"]}).status_code == 200


def test_an_item_reads_in_full_with_its_signed_notes(client):
    c, _ = client
    _add(c, description="Why it matters.")
    c.post("/backlog/alpha-project/ap1/notes", json={"note": "Found the slow path.", "status": "doing"})
    r = c.get("/backlog/alpha-project/AP1")
    assert r.status_code == 200 and r.headers["etag"]
    item = r.json()
    assert item["description"] == "Why it matters." and item["status"] == "doing"
    note = item["notes"][0]
    assert (note["day"], note["by"], note["byKind"], note["byLabel"]) == ("2026-09-24", "user", "user", "You")
    assert note["text"] == "Found the slow path.\n\nMoved from open to doing." and note["at"] == "2026-09-24T18:00:00Z"
    assert note["authorModel"] is None and note["authorEffort"] is None           # R-B6: C3 lands these
    assert c.get("/backlog/alpha-project/AP9").status_code == 404
    assert c.get("/backlog/bob-example/AP1").status_code == 404                     # not a project


def test_edits_and_refusals_speak_in_status_codes(client):
    c, _ = client
    _add(c)
    r = c.patch("/backlog/alpha-project/AP1", json={"title": "Cache it", "status": "done", "triage": "research"})
    assert r.status_code == 200 and (r.json()["title"], r.json()["status"], r.json()["triage"]) == (
        "Cache it", "done", "research")
    assert r.json()["notes"][-1]["text"] == "Moved from open to done."
    assert c.patch("/backlog/alpha-project/AP1", json={}).status_code == 400
    assert c.post("/backlog/alpha-project/AP1/notes", json={"note": "  "}).status_code == 400
    assert c.post("/projects/no-such-project/backlog", json={"title": "x"}).status_code == 404
    _add(c, "Second idea")
    dup = _add(c, "second IDEA")
    assert dup.status_code == 409 and dup.json()["detail"].startswith("AP2 already holds this")


def test_every_write_waits_while_sleep_runs(client, monkeypatch):
    c, bank = client
    _add(c)
    monkeypatch.setattr(sleep_cycle, "get_sleep_state", lambda: SimpleNamespace(status="running"))
    head = _git(bank, "rev-parse", "HEAD")
    calls = [("post", "/projects/alpha-project/backlog", {"title": "X"}),
             ("post", "/backlog/alpha-project/AP1/notes", {"note": "Y"}),
             ("patch", "/backlog/alpha-project/AP1", {"status": "done"}),
             ("post", "/projects/alpha-project/backlog/import", {"markdown": "| G1 | **X** | y | 🔲 |"})]
    for method, url, body in calls:
        r = getattr(c, method)(url, json=body)
        assert r.status_code == 409 and r.json()["detail"] == backlog_router.BUSY, url
    assert _git(bank, "rev-parse", "HEAD") == head


def test_the_import_route_files_rows_once(client):
    c, bank = client
    text = ("| ID | Item | Notes | Status |\n|----|------|-------|--------|\n"
            "| G1 | **Cache it** | why | ✅ done |\n| G2 | **Index it** | why | 🔲 |\n")
    first = c.post("/projects/alpha-project/backlog/import", json={"markdown": text})
    assert first.status_code == 200 and first.json() == {"created": ["G1", "G2"], "skipped": [], "failed": []}
    log = _git(bank, "log", "-1", "--format=%B")
    assert log.startswith("Backlog import 2026-09-24") and "trigger: user/backlog_import" in log
    head = _git(bank, "rev-parse", "HEAD")
    second = c.post("/projects/alpha-project/backlog/import", json={"markdown": text})
    assert second.json() == {"created": [], "skipped": ["G1", "G2"], "failed": []}
    assert _git(bank, "rev-parse", "HEAD") == head
    assert c.post("/projects/alpha-project/backlog/import", json={"markdown": text, "prefix": "g1"}).status_code == 400
```

Create `api/tests/test_backlog_import.py`:

```python
"""G150 R-B15 — a markdown backlog in this repository's G-row shape files into a project's backlog, keeping ids
and states, and a second run changes nothing. The file below is SYNTHETIC, shaped like the real one."""
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from _synthetic_bank import _bank
from api.services import backlog, backlog_import, bank_index

NOW = datetime(2026, 9, 24, 10, 0, tzinfo=timezone.utc)
ALL = ["G1", "G2", "G3", "G4", "G5", "G6", "G7"]
SYNTHETIC = """# Goal: an example backlog

## APPLY — buildable now

| ID | Item | Notes | Status |
|----|------|-------|--------|
| G1 | **Cache the timeline** (bob-example 2026-08-01: "it's slow") | `_tree` re-reads pages; see PR #12. | ✅ shipped (PR #12) |
| G2 💸 | **Re-extract with a big model** | Costs a paid run \\| worth it later. | 🔲 |
| G3 | *(merged into [G1](#g1) — same fix)* | — | — |

## DESIGN — new structures (2026-08-20)

| ID | Item | Notes | Status |
|----|------|-------|--------|
| G4 | **Pick a storage shape** | Two options. | ❓ |
| G5 | **Read the other system's docs** | Compare. | 🛠️ slice 1 ✅ (PR #30); slice 2 open |
| R1 | Not a G row | ignored | 🔲 |

### G6 — Write the assembly checklist 💸

Status: 🔬 researching
Step by step, with photos.

### G7: A section with no status
Plain body.
"""


@pytest.fixture
def bank(tmp_path):
    memory = _bank(tmp_path, git=False)
    bank_index.invalidate()
    return memory


def _git(bank, *args):
    return subprocess.run(["git", *args], cwd=bank, capture_output=True, text=True, check=True).stdout


def test_the_file_reads_as_rows_of_one_prefix():
    rows = {r.id: r for r in backlog_import.parse(SYNTHETIC)}
    assert list(rows) == ALL
    assert rows["G1"].title == "Cache the timeline" and rows["G1"].created == "2026-08-01"
    assert rows["G1"].description.startswith('(bob-example 2026-08-01: "it\'s slow")')
    assert rows["G2"].paid and rows["G2"].description == "Costs a paid run | worth it later."
    assert rows["G3"].title == "merged into G1 — same fix"
    assert rows["G4"].created == "2026-08-20" and rows["G4"].triage is None
    assert rows["G6"].paid and rows["G6"].status_cell == "🔬 researching"
    assert rows["G6"].description == "Step by step, with photos." and rows["G6"].title == "Write the assembly checklist"
    assert rows["G7"].title == "A section with no status" and rows["G7"].description == "Plain body."
    assert [r.id for r in backlog_import.parse(SYNTHETIC, prefix="R")] == ["R1"]


@pytest.mark.parametrize("cell,expected", [
    ("✅ shipped", ("done", None)), ("🛠️ slice 1 ✅; slice 2 open", ("doing", None)), ("🔲", ("open", None)),
    ("❓", ("open", "decide")), ("🔬 researching", ("doing", "research")), ("🅿️ parked", ("open", None)),
    ("🟡 PJ-1 built", ("doing", None)), ("—", ("dropped", None)), ("**Closed 2026-09-01**", ("dropped", None)),
    ("", ("open", None)), ("see the notes", ("open", None)),
])
def test_the_first_mark_decides_the_status(cell, expected):
    assert backlog_import.status_of(cell) == expected


def test_an_import_keeps_ids_and_states_and_a_second_run_changes_nothing(bank):
    first = backlog_import.import_markdown(bank, project="alpha-project", text=SYNTHETIC, now=NOW, tz_name="UTC")
    assert (first.created, first.skipped, first.failed, first.error) == (ALL, [], [], None)
    items = {i.id: i for i in backlog.list_items(bank, "alpha-project")}
    assert {k: (v.status, v.triage, v.paid) for k, v in items.items()} == {
        "G1": ("done", "apply", False), "G2": ("open", "apply", True), "G3": ("dropped", "apply", False),
        "G4": ("open", "decide", False), "G5": ("doing", None, False), "G6": ("doing", "research", True),
        "G7": ("open", None, False)}
    g1 = backlog.get_item(bank, "alpha-project", "G1")
    assert g1.created == "2026-08-01" and g1.links == [{"kind": "pr", "ref": "#12"}]
    assert g1.notes[0].text == "Imported from a backlog file. Its status there: ✅ shipped (PR #12)"
    assert g1.notes[0].by == "user" and items["G2"].created == "2026-09-24"          # no date anywhere: today
    folder = bank / "backlog" / "alpha-project"
    before = {p.name: p.read_bytes() for p in folder.glob("*.md")}
    second = backlog_import.import_markdown(bank, project="alpha-project", text=SYNTHETIC, now=NOW, tz_name="UTC")
    assert (second.created, second.skipped, second.paths) == ([], ALL, [])
    assert {p.name: p.read_bytes() for p in folder.glob("*.md")} == before
    nxt = backlog.add_item(bank, project="alpha-project", title="Next idea", author="user", now=NOW, tz_name="UTC")
    assert nxt["item"].id == "G8"                                                      # R-B2: the sequence continues


def test_a_long_title_is_cut_at_a_word_and_kept_whole_in_the_description(bank):
    long = " ".join(["word"] * 60)
    text = f"| ID | Item | Notes | Status |\n|--|--|--|--|\n| G1 | **{long}** | why | 🔲 |\n"
    backlog_import.import_markdown(bank, project="alpha-project", text=text, now=NOW, tz_name="UTC")
    g1 = backlog.get_item(bank, "alpha-project", "G1")
    assert len(g1.title) <= backlog.TITLE_CHARS and g1.title.endswith("…")
    assert g1.description.startswith(long)


def test_an_import_refuses_what_it_cannot_file(bank):
    assert backlog_import.import_markdown(bank, project="no-such-project", text=SYNTHETIC).error
    assert backlog_import.import_markdown(bank, project="alpha-project", text=SYNTHETIC, prefix="g1").error
    too_big = "x" * (backlog_import.MAX_CHARS + 1)
    assert backlog_import.import_markdown(bank, project="alpha-project", text=too_big).error
    assert not (bank / "backlog").exists()


def test_import_file_commits_once_as_the_person(tmp_path):
    bank = _bank(tmp_path)                                                              # a git bank
    src = tmp_path / "backlog.md"
    src.write_text(SYNTHETIC, encoding="utf-8")
    report = backlog_import.import_file(bank, "alpha-project", src)
    log = _git(bank, "log", "-1", "--format=%B")
    assert log.startswith("Backlog import ") and "Cicada-Author: user" in log
    assert "trigger: user/backlog_import" in log
    assert sorted(_git(bank, "show", "--name-only", "--format=", "HEAD").split()) == sorted(report.paths)
    head = _git(bank, "rev-parse", "HEAD")
    assert backlog_import.import_file(bank, "alpha-project", src).created == []
    assert _git(bank, "rev-parse", "HEAD") == head


def test_the_script_runs_twice_and_the_second_run_changes_nothing(tmp_path):
    bank = _bank(tmp_path)
    src = tmp_path / "backlog.md"
    src.write_text(SYNTHETIC, encoding="utf-8")
    script = Path(__file__).resolve().parents[2] / "scripts" / "import-backlog.sh"
    env = {**os.environ, "CICADA_TELEMETRY": "off", "CICADA_HOME": str(tmp_path / "home")}

    def run():
        done = subprocess.run(["bash", str(script), str(bank), "alpha-project", str(src)], capture_output=True,
                              text=True, env=env)
        assert done.returncode == 0, done.stderr
        return json.loads(done.stdout)

    assert run() == {"created": 7, "skipped": 0, "failed": [], "error": None}
    head = _git(bank, "rev-parse", "HEAD")
    assert run() == {"created": 0, "skipped": 7, "failed": [], "error": None}
    assert _git(bank, "rev-parse", "HEAD") == head
```

Create `api/tests/test_backlog_app_fixture.py`:

```python
"""G150 (R-B26) — the app's backlog fixture IS the server's wire on the demo scenario (R-PP27's precedent: two
languages, one table). Regenerate after a deliberate wire change:
`CICADA_WRITE_APP_FIXTURE=1 api/.venv/bin/python -m pytest api/tests/test_backlog_app_fixture.py`."""
import json
import os
import re
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from _demo_scenario import T, demo
from api import config, main
from api.services import bank_index, handshake

FIXTURE = Path(__file__).resolve().parents[2] / "app" / "CicadaApp" / "Tests" / "fixtures" / "backlog-demo.json"


def _wire(tmp_path, monkeypatch) -> tuple[dict, Path]:
    bank = demo(tmp_path, index=False)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    monkeypatch.setattr(handshake, "local_timezone", lambda: "UTC")
    config.get_settings.cache_clear()
    bank_index.invalidate()
    try:
        c = TestClient(main.app)
        return {"today": T.isoformat(), "list": c.get("/projects/rover-arm-project/backlog").json(),
                "item": c.get("/backlog/rover-arm-project/RAP3").json()}, bank
    finally:
        config.get_settings.cache_clear()


def test_the_app_fixture_is_the_demo_wire(tmp_path, monkeypatch):
    wire, _bank = _wire(tmp_path, monkeypatch)
    text = json.dumps(wire, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    if os.environ.get("CICADA_WRITE_APP_FIXTURE") == "1":
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(text, encoding="utf-8")
    assert FIXTURE.read_text(encoding="utf-8") == text, (
        "the app's fixture drifted from the demo wire — rerun with CICADA_WRITE_APP_FIXTURE=1 after a deliberate change")


def test_the_demo_backlog_reads_as_the_rulings_say(tmp_path, monkeypatch):
    wire, bank = _wire(tmp_path, monkeypatch)
    listed = wire["list"]
    assert listed["prefix"] == "RAP" and listed["counts"] == {"open": 2, "doing": 1, "done": 1, "dropped": 1}
    assert [i["id"] for i in listed["items"]] == ["RAP5", "RAP3", "RAP4", "RAP2", "RAP1"]
    notes = wire["item"]["notes"]
    assert [(n["byLabel"], n["byKind"]) for n in notes] == [("Claude Code", "harness"), ("You", "user")]
    assert notes[0]["session"] == "ses_demo_rover_02" and all(n["authorModel"] is None for n in notes)
    log = subprocess.run(["git", "-C", str(bank), "log", "--format=%s%n%b---END---"], check=True, capture_output=True,
                         text=True).stdout.split("---END---")
    backlog_commits = [c for c in log if "backlog/rover-arm-project/" in c]
    assert len(backlog_commits) == 10                        # five items + five notes, each alone (R-B26)
    assert all(("Cicada-Author: user" in c and "trigger: user/companion_app" in c)
               or ("Cicada-Author: claude-code" in c and "trigger: mcp/claude-code" in c
                   and "Cicada-Session: ses_demo_rover_02" in c) for c in backlog_commits)


def test_the_fixture_is_synthetic():
    """Privacy (CLAUDE.md): demo fiction only, every URL on example.com, no machine path."""
    raw = FIXTURE.read_text(encoding="utf-8")
    assert "/Users/" not in raw and "/private/" not in raw and "/home/" not in raw
    for url in re.findall(r"https?://[^\s\"']+", raw):
        assert url.split("/")[2].endswith("example.com"), url
```

Run: `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_backlog_router.py api/tests/test_backlog_import.py
api/tests/test_backlog_app_fixture.py -q -p no:cacheprovider` → the router is 404 everywhere, `backlog_import` does
not import, and the fixture file does not exist. That is the red.

- [ ] **Step 2: The schemas.** In `api/models/schemas.py`, after `ProjectWriteResponse` (`:1247-1253`), add:

```python
# --- G150: a project's backlog (routers/backlog.py) ----------------------------


class BacklogLink(CamelModel):
    kind: str                      # pr | commit | url | doc | entity
    ref: str


class BacklogNoteModel(CamelModel):
    """One signed note (R-B4). `by` is the author id, `byLabel` the heading's
    words. `authorModel`/`authorEffort` are the turn's model and effort for a
    harness note once round 4's C3 join is called in `routers/backlog._note`
    (R-B6) — null until then, never self-reported."""
    day: str
    text: str
    by: str
    by_kind: str
    by_provider: Optional[str] = None
    by_label: str
    at: Optional[str] = None
    session: Optional[str] = None
    author_model: Optional[str] = None
    author_effort: Optional[str] = None


class BacklogItemSummary(CamelModel):
    id: str
    project: str
    title: str
    status: str                    # open | doing | done | dropped
    triage: Optional[str] = None   # apply | research | decide
    paid: bool = False
    created: str
    updated: str
    added_by: str
    added_by_kind: str
    added_by_label: str
    note_count: int = 0
    last_note_day: Optional[str] = None   # the machine zone's day (tzName) — never a relative word
    last_note_by: Optional[str] = None
    order: Optional[int] = None


class BacklogItemModel(BacklogItemSummary):
    description: str = ""
    notes: list[BacklogNoteModel] = []
    links: list[BacklogLink] = []
    session: Optional[str] = None
    path: str = ""


class BacklogListResponse(CamelModel):
    project: str
    project_name: str
    prefix: str
    counts: dict[str, int]
    items: list[BacklogItemSummary]
    tz_name: str


class BacklogItemCreate(CamelModel):
    title: str
    description: str = ""
    triage: Optional[str] = None
    paid: bool = False


class BacklogNoteCreate(CamelModel):
    note: str = ""
    status: Optional[str] = None


class BacklogItemPatch(CamelModel):
    title: Optional[str] = None
    status: Optional[str] = None
    triage: Optional[str] = None   # "" clears it
    paid: Optional[bool] = None
    links: Optional[list[BacklogLink]] = None


class BacklogImportRequest(CamelModel):
    markdown: str
    prefix: str = "G"


class BacklogImportResponse(CamelModel):
    created: list[str]
    skipped: list[str]
    failed: list[str] = []
```

- [ ] **Step 3: The router.** Create `api/routers/backlog.py`:

```python
"""G150 — a project's backlog over HTTP (R-B7, R-B8, R-B18).

Six routes over the ONE writer (`services/backlog.py`): two reads, the
person's three writes, and the importer's live path (R-B15).

The reads are fetched on demand, like the Projects reads (R-PJ7): neither is a
Store domain, so there is no `VersionVector` mapping and the ship-together
rule has nothing to pair. Both ETags fold the `backlog` component (every item
file's stamp) and `entities` (the project's name and `backlog_prefix:`), plus
`BACKLOG_SHAPE`, `git_service.AUTHOR_SHAPE` — the body carries an author kind
(the G118 rule) — and the machine zone's NAME, because `lastNoteDay` is a day
in it. Never today.

The person's writes are `Cicada-Author: user`, trigger `user/companion_app`
(an import: `user/backlog_import`), each committed alone over the item's own
file (R-B7), and every one answers 409 while Sleep runs (R-B8, the
`routers/projects.py` precedent): Sleep's `_finalize` stages with
`git add -A`, so a file written between its read and its commit would ride the
cycle's commit under a model's name. This module decides nothing about
validity — it picks the project, the author, the clock and the status code.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from loguru import logger
from starlette.concurrency import run_in_threadpool

from api.config import Settings, get_settings
from api.models.schemas import (BacklogImportRequest, BacklogImportResponse, BacklogItemCreate, BacklogItemModel,
                                BacklogItemPatch, BacklogItemSummary, BacklogLink, BacklogListResponse,
                                BacklogNoteCreate, BacklogNoteModel)
from api.services import backlog, backlog_import, git_service, handshake, sync_service, when

router = APIRouter()

# One write at a time in this process (the `routers/projects.py` reason): two
# quick taps would read the same file before either commit ran. Across
# processes the item file's own lock holds (`backlog._locked`).
_write_lock = asyncio.Lock()
BUSY = "Sleep is writing memory right now, try again in a moment"
TRIGGER = "user/companion_app"


def _tz() -> str:
    return handshake.local_timezone() or "UTC"


def _now() -> datetime:
    """The one clock every write here reads — a seam so tests pin a day."""
    return datetime.now(when.zone(_tz()))


def _guard() -> None:
    from api.services import sleep_cycle

    if sleep_cycle.get_sleep_state().status == "running":
        raise HTTPException(409, BUSY)


def _project(memory_path, project_id: str) -> tuple[str, dict]:
    got = backlog.project_page(memory_path, project_id)
    if isinstance(got, dict):
        raise HTTPException(404, got["error"])
    return got


def _etag(memory_path, *parts: str) -> str:
    extra = "|".join(["backlog", *parts, backlog.BACKLOG_SHAPE, git_service.AUTHOR_SHAPE, _tz()])
    return sync_service.etag_for(memory_path, "backlog", "entities", extra=extra)


def _raise_for(result: dict) -> None:
    action = result.get("action")
    if action == "not_found":
        raise HTTPException(404, result.get("error") or "Not found")
    if action in ("duplicate", "exists"):
        raise HTTPException(409, result.get("error") or "That's already on the backlog")
    if action == "error":
        raise HTTPException(400, result.get("error") or "That couldn't be saved")


def _summary(item: backlog.Item, tz: str) -> BacklogItemSummary:
    kind, _provider = git_service.author_identity(item.added_by)
    return BacklogItemSummary(
        id=item.id, project=item.project, title=item.title, status=item.status, triage=item.triage,
        paid=item.paid, created=item.created, updated=item.updated, added_by=item.added_by, added_by_kind=kind,
        added_by_label=backlog.who_label(item.added_by), note_count=item.note_count,
        last_note_day=backlog.local_day(item.last_note_at, tz), last_note_by=item.last_note_by, order=item.order)


def _note(note: backlog.Note) -> BacklogNoteModel:
    """R-B6's seam: once round 4's C3 join is on `dev`, its one helper is
    called here with `(note.session, note.at)` to fill `author_model` and
    `author_effort` — never a second implementation of that join."""
    by = backlog.author_of(note)
    kind, provider = git_service.author_identity(by)
    return BacklogNoteModel(day=note.day, text=note.text, by=by, by_kind=kind, by_provider=provider,
                            by_label=note.who, at=note.at, session=note.session)


def _item(item: backlog.Item, tz: str) -> BacklogItemModel:
    return BacklogItemModel(**_summary(item, tz).model_dump(by_alias=False), description=item.description,
                            notes=[_note(n) for n in item.notes],
                            links=[BacklogLink(**link) for link in item.links], session=item.session,
                            path=item.path)


async def _commit(memory_path, paths: list[str], action: str, *, subject: str = "Backlog update",
                  trigger: str = TRIGGER) -> None:
    if not paths:
        return
    message = backlog.commit_message(paths, action=action, subject=subject, trigger=trigger,
                                     day=_now().date().isoformat())
    try:
        await git_service.commit_paths(memory_path, message, sorted(set(paths)))
    except Exception as exc:  # noqa: BLE001 — the write stands; a later writer's commit picks it up
        logger.warning(f"backlog commit skipped: {type(exc).__name__}")


# --------------------------------------------------------------------------- #
# reads
# --------------------------------------------------------------------------- #


@router.get("/projects/{project_id}/backlog", response_model=BacklogListResponse)
async def list_backlog(project_id: str, request: Request, response: Response, status: Optional[str] = None,
                       settings: Settings = Depends(get_settings)):
    mp = settings.memory_path
    stem, fm = _project(mp, project_id)
    if status is not None and status not in backlog.STATUSES:
        raise HTTPException(400, f"status is one of {', '.join(backlog.STATUSES)}")
    etag = _etag(mp, "list", stem, status or "")
    if (early := sync_service.conditional(request, response, etag)) is not None:
        return early
    tz = _tz()

    def build() -> BacklogListResponse:
        items = backlog.list_items(mp, stem)
        shown = [i for i in items if status is None or i.status == status]
        return BacklogListResponse(project=stem, project_name=str(fm.get("name") or stem),
                                   prefix=backlog.prefix_for(mp, stem, fm), counts=backlog.counts(items),
                                   items=[_summary(i, tz) for i in shown], tz_name=tz)

    return await run_in_threadpool(build)


@router.get("/backlog/{project_id}/{item_id}", response_model=BacklogItemModel)
async def get_backlog_item(project_id: str, item_id: str, request: Request, response: Response,
                           settings: Settings = Depends(get_settings)):
    mp = settings.memory_path
    stem, _ = _project(mp, project_id)
    iid = backlog.normalize_id(item_id)
    if iid is None:
        raise HTTPException(404, f"{item_id!r} isn't an item id")
    etag = _etag(mp, "item", stem, iid)
    if (early := sync_service.conditional(request, response, etag)) is not None:
        return early
    item = await run_in_threadpool(backlog.get_item, mp, stem, iid)
    if item is None:
        raise HTTPException(404, f"No {iid} on this project's backlog")
    return _item(item, _tz())


# --------------------------------------------------------------------------- #
# the person's writes
# --------------------------------------------------------------------------- #


@router.post("/projects/{project_id}/backlog", response_model=BacklogItemModel)
async def add_backlog_item(project_id: str, body: BacklogItemCreate, settings: Settings = Depends(get_settings)):
    _guard()
    mp = settings.memory_path
    stem, _ = _project(mp, project_id)
    async with _write_lock:
        result = await run_in_threadpool(
            backlog.add_item, mp, project=stem, title=body.title, description=body.description,
            triage=body.triage, paid=body.paid, author=backlog.USER, now=_now(), tz_name=_tz())
        _raise_for(result)
        await _commit(mp, result["paths"], "created")
    return _item(result["item"], _tz())


@router.post("/backlog/{project_id}/{item_id}/notes", response_model=BacklogItemModel)
async def add_backlog_note(project_id: str, item_id: str, body: BacklogNoteCreate,
                           settings: Settings = Depends(get_settings)):
    _guard()
    mp = settings.memory_path
    stem, _ = _project(mp, project_id)
    async with _write_lock:
        result = await run_in_threadpool(
            backlog.add_note, mp, project=stem, item=item_id, note=body.note, status=body.status,
            author=backlog.USER, now=_now(), tz_name=_tz())
        _raise_for(result)
        await _commit(mp, result["paths"], "updated")
    return _item(result["item"], _tz())


@router.patch("/backlog/{project_id}/{item_id}", response_model=BacklogItemModel)
async def change_backlog_item(project_id: str, item_id: str, body: BacklogItemPatch,
                              settings: Settings = Depends(get_settings)):
    _guard()
    mp = settings.memory_path
    stem, _ = _project(mp, project_id)
    links = None if body.links is None else [link.model_dump(by_alias=False) for link in body.links]
    async with _write_lock:
        result = await run_in_threadpool(
            backlog.update_item, mp, project=stem, item=item_id, title=body.title, status=body.status,
            triage=body.triage, paid=body.paid, links=links, author=backlog.USER, now=_now(), tz_name=_tz())
        _raise_for(result)
        await _commit(mp, result["paths"], "updated")
    return _item(result["item"], _tz())


@router.post("/projects/{project_id}/backlog/import", response_model=BacklogImportResponse)
async def import_backlog(project_id: str, body: BacklogImportRequest, settings: Settings = Depends(get_settings)):
    """R-B15's live path: one `Backlog import` commit as the person, or none —
    an id already on the backlog is skipped, so a second post changes nothing."""
    _guard()
    mp = settings.memory_path
    stem, _ = _project(mp, project_id)
    if len(body.markdown) > backlog_import.MAX_CHARS:
        raise HTTPException(413, "That file is too large to import")
    async with _write_lock:
        report = await run_in_threadpool(
            backlog_import.import_markdown, mp, project=stem, text=body.markdown, prefix=body.prefix,
            author=backlog.USER, now=_now(), tz_name=_tz())
        if report.error:
            raise HTTPException(400, report.error)
        await _commit(mp, report.paths, "created", subject="Backlog import", trigger=backlog_import.IMPORT_TRIGGER)
    return BacklogImportResponse(created=report.created, skipped=report.skipped, failed=report.failed)
```

Mount it in `api/main.py`: add `backlog,` to the `from api.routers import (…)` list (after `ask,`) and
`app.include_router(backlog.router, tags=["backlog"])` on the line after `projects.router` (`:209`).

- [ ] **Step 4: The importer.** Create `api/services/backlog_import.py`:

```python
"""G150 R-B15 — file an existing markdown backlog into a project's backlog.

The shape it reads is this repository's own. `docs/goals/memory-evolution.md`
keeps one table row per idea — `| G<n>[ 💸] | **Title** (the owner's words) |
the reasoning | status |` — under `## ` headings that may name a triage, and a
backlog elsewhere may keep `### G<n> — Title` sections with a `Status:` line.
Both are read, for ONE id prefix per run (default `G`, so a file's `R1`
research rows are not filed); nothing else in the file is.

Ids and states are kept — a G-id is a permanent address (CLAUDE.md) — the raw
status cell survives as the first note, and an id already on the backlog is
skipped, never updated: the bank's copy may hold notes the file does not. A
second run therefore changes nothing and commits nothing. Every row goes
through `backlog.add_item` (the ONE writer), so the scrub and the file shape
are every other door's.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from loguru import logger

from api.services import backlog

MAX_CHARS = 2_000_000
IMPORT_TRIGGER = "user/backlog_import"
PAID = "💸"
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_DATE = re.compile(r"\b(20\d\d-\d\d-\d\d)\b")
_PR = re.compile(r"\bPR\s*#(\d+)")
_CELL = re.compile(r"(?<!\\)\|")
_HEADING = re.compile(r"^#{1,3}\s")
_STATUS_LINE = re.compile(r"^\s*(?:\*\*)?status(?:\*\*)?\s*:\s*(?:\*\*)?\s*(?P<s>.+?)\s*$", re.I)
# R-B15: the FIRST mark in a status cell wins ("🛠️ slice 1 ✅; slice 2 open" is
# still under way). A variation selector after a mark (🛠️, 🅿️) does not
# matter to `in`.
_MARKS = (("✅", "done"), ("🛠", "doing"), ("🟡", "doing"), ("🔬", "doing"),
          ("🔲", "open"), ("❓", "open"), ("🅿", "open"))
_HINTS = {"❓": "decide", "🔬": "research"}
_TRIAGE_WORDS = {"APPLY": "apply", "RESEARCH": "research", "DECIDE": "decide"}


@dataclass
class Row:
    id: str
    title: str
    description: str
    status_cell: str
    triage: str | None
    paid: bool
    created: str | None


@dataclass
class ImportReport:
    created: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)
    error: str | None = None


def status_of(cell: str) -> tuple[str, str | None]:
    """`(status, triage hint)` for a status cell: the first mark decides;
    with none, "merged", "closed" or a bare dash mean the row was set aside."""
    text = cell or ""
    hits = sorted((text.find(mark), state, mark) for mark, state in _MARKS if mark in text)
    if hits:
        _pos, state, mark = hits[0]
        return state, _HINTS.get(mark)
    low = text.strip().lower()
    if low in ("—", "–", "-") or "merged" in low or "closed" in low:
        return "dropped", None
    return "open", None


def _cells(line: str) -> list[str]:
    parts = _CELL.split(line.strip())
    return [p.strip().replace("\\|", "|") for p in parts[1:-1]]


def _plain(text: str) -> str:
    text = _MD_LINK.sub(r"\1", text or "")
    return " ".join(re.sub(r"[*_`]", "", text).split()).strip(" ()")


def _title(cell: str) -> tuple[str, str]:
    """The item cell's first bold span is the brief task; what surrounds it
    (the owner's quoted words, a date) opens the description. A row with no
    bold span — a merged row's italic note — is its own title."""
    m = _BOLD.search(cell or "")
    if m is None:
        return _plain(cell), ""
    return _plain(m.group(1)), (cell[: m.start()] + cell[m.end():]).strip()


def _table_row(cells: list[str], triage: str | None, heading_date: str | None) -> Row:
    title, rest = _title(cells[1])
    if len(cells) >= 4:
        reasoning, status_cell = " | ".join(cells[2:-1]), cells[-1]
    else:
        reasoning, status_cell = cells[2], ""
    date = _DATE.search(cells[1])
    return Row(id=cells[0].replace(PAID, "").strip(), title=title,
               description="\n\n".join(x for x in (rest, reasoning) if x.strip()), status_cell=status_cell.strip(),
               triage=triage, paid=PAID in cells[0], created=date.group(1) if date else heading_date)


def _section_row(iid: str, heading_rest: str, body: list[str], triage: str | None,
                 heading_date: str | None) -> Row:
    status_cell, kept = "", []
    for line in body:
        m = _STATUS_LINE.match(line)
        if m and not status_cell:
            status_cell = m.group("s")
        else:
            kept.append(line)
    title = _plain(heading_rest.replace(PAID, "").strip().lstrip("—–:·- ").strip())
    date = _DATE.search(heading_rest)
    return Row(id=iid, title=title, description="\n".join(kept).strip(), status_cell=status_cell.strip(),
               triage=triage, paid=PAID in heading_rest, created=date.group(1) if date else heading_date)


def parse(text: str, prefix: str = "G") -> list[Row]:
    """Every row of `prefix` in `text`, in file order. An id seen twice keeps
    its first row — a later mention is a cross-reference, not a new idea."""
    pre = re.escape(prefix)
    head_id = re.compile(rf"^({pre}\d{{1,6}}[a-z]?)\s*(?:{PAID})?\s*$")
    section = re.compile(rf"^###\s+({pre}\d{{1,6}}[a-z]?)\b(.*)$")
    rows: list[Row] = []
    triage: str | None = None
    heading_date: str | None = None
    lines = (text or "").splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("## "):
            triage = _TRIAGE_WORDS.get(line[3:].strip().split(" ", 1)[0].strip("*").upper())
            m = _DATE.search(line)
            heading_date = m.group(1) if m else None
            i += 1
            continue
        s = section.match(line)
        if s:
            body: list[str] = []
            j = i + 1
            while j < len(lines) and not _HEADING.match(lines[j]):
                body.append(lines[j])
                j += 1
            rows.append(_section_row(s.group(1), s.group(2), body, triage, heading_date))
            i = j
            continue
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = _cells(stripped)
            if len(cells) >= 3 and head_id.match(cells[0]):
                rows.append(_table_row(cells, triage, heading_date))
        i += 1
    seen: set[str] = set()
    out: list[Row] = []
    for row in rows:
        if row.id not in seen:
            seen.add(row.id)
            out.append(row)
    return out


def _cut(title: str) -> str:
    if len(title) <= backlog.TITLE_CHARS:
        return title
    cut = title[: backlog.TITLE_CHARS - 1].rsplit(" ", 1)[0].rstrip(" ,;:—–-")
    return f"{cut}…"


def _links(row: Row) -> list[dict]:
    refs = dict.fromkeys(f"#{n}" for n in _PR.findall(f"{row.description}\n{row.status_cell}"))
    return [{"kind": "pr", "ref": r} for r in refs][: backlog.MAX_LINKS]


def import_markdown(memory_path: Path, *, project: str, text: str, prefix: str = "G", author: str = backlog.USER,
                    now: datetime | None = None, tz_name: str | None = None) -> ImportReport:
    """File every `prefix` row of `text` on `project`'s backlog. Never raises;
    commits nothing — the caller commits `report.paths` (R-B7)."""
    report = ImportReport()
    prefix = (prefix or "").strip()
    if not re.fullmatch(r"[A-Z]{1,6}", prefix):
        report.error = "a prefix is 1 to 6 capital letters, like G"
        return report
    if len(text or "") > MAX_CHARS:
        report.error = "that file is too large to import"
        return report
    got = backlog.project_page(Path(memory_path), project)
    if isinstance(got, dict):
        report.error = got["error"]
        return report
    stem = got[0]
    for row in parse(text, prefix):
        title = _cut(row.title)
        description = row.description if title == row.title else f"{row.title}\n\n{row.description}".strip()
        status, hint = status_of(row.status_cell)
        note = ("Imported from a backlog file. Its status there: " + row.status_cell) if row.status_cell \
            else "Imported from a backlog file."
        result = backlog.add_item(memory_path, project=stem, title=title, description=description, author=author,
                                  triage=row.triage or hint, paid=row.paid, links=_links(row), status=status,
                                  item_id=row.id, created=row.created, first_note=note, now=now, tz_name=tz_name)
        action = result.get("action")
        if action == "added":
            report.created.append(row.id)
            report.paths += result["paths"]
        elif action == "exists":
            report.skipped.append(row.id)
        else:
            report.failed.append(row.id)
            logger.warning(f"backlog import: {row.id} not filed ({action})")
    return report


def import_file(memory_path: Path, project: str, source: Path, *, prefix: str = "G") -> ImportReport:
    """`scripts/import-backlog.sh`'s entry point: read, import, and commit what
    was created in ONE `Backlog import` commit as the person — or none."""
    from api.services import git_service, handshake, when

    memory_path = Path(memory_path)
    report = import_markdown(memory_path, project=project, text=Path(source).read_text(encoding="utf-8"),
                             prefix=prefix)
    if report.paths and (memory_path / ".git").exists():
        day = datetime.now(when.zone(handshake.local_timezone())).date().isoformat()
        git_service.commit_paths_sync(memory_path, backlog.commit_message(
            report.paths, action="created", subject="Backlog import", trigger=IMPORT_TRIGGER, day=day), report.paths)
    return report
```

Create `scripts/import-backlog.sh` and `chmod +x` it:

```bash
#!/usr/bin/env bash
#
# import-backlog.sh — G150 R-B15: file a markdown backlog (G-row table rows
# and/or `### G<n>` sections) into ONE project's backlog in a bank, keeping
# ids and statuses. Idempotent: an id already on the backlog is skipped, so a
# second run changes nothing and commits nothing. What it creates lands in one
# `Backlog import` commit as the person (`Cicada-Author: user`, trigger
# `user/backlog_import`).
#
# It writes the named bank directly, in-process: run it on a bank the backend
# is not consolidating (the live path is `POST /projects/{id}/backlog/import`,
# which answers 409 while Sleep runs). Its output is counts and ids only —
# never a title or a description — so it can be pasted anywhere.
#
#   scripts/import-backlog.sh <bank-dir> <project-id> <file.md> [prefix]
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"   # portability: no author-machine path
BANK="${1:-}"
PROJECT="${2:-}"
FILE="${3:-}"
PREFIX="${4:-G}"
if [[ -z "$BANK" || -z "$PROJECT" || -z "$FILE" || ! -d "$BANK/entities" || ! -f "$FILE" ]]; then
  echo "usage: scripts/import-backlog.sh <bank-dir> <project-id> <file.md> [prefix]" >&2
  exit 2
fi
BANK="$(cd "$BANK" && pwd)"
FILE="$(cd "$(dirname "$FILE")" && pwd)/$(basename "$FILE")"
PY="$REPO/api/.venv/bin/python"
[[ -x "$PY" ]] || PY="$(command -v python3)"

cd "$REPO"
"$PY" - "$BANK" "$PROJECT" "$FILE" "$PREFIX" <<'PYEOF'
import json
import sys
from pathlib import Path

from api.services import backlog_import

report = backlog_import.import_file(Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]), prefix=sys.argv[4])
print(json.dumps({"created": len(report.created), "skipped": len(report.skipped), "failed": report.failed,
                  "error": report.error}))
sys.exit(1 if report.error or report.failed else 0)
PYEOF
```

- [ ] **Step 5: The demo's backlog.** Append to `api/services/demo_bank.py` (after `_write_scenario_followups`, so
  `_AGENT_SESSION` is defined above it):

```python
# --- G150 (R-B26): the scenario's backlog, through the one backlog writer ------
#
# (offset, author, session, title, triage, description), filed in this order so
# the ids read RAP1…RAP5 oldest first; then (offset, item, author, session,
# note, status). Every write commits at once under its own author, so an item
# the person and an agent both touched keeps exact provenance.

_BACKLOG_ITEMS = (
    (-40, "user", None, "Write the assembly checklist", "apply",
     "Assembly took three tries because nothing was written down. A checklist with the torque values and the "
     "cable routing would make the next build one afternoon."),
    (-20, "user", None, "Try a second tray camera", None,
     "A second angle might help the grasp planner with parts that hide behind each other."),
    (-12, "claude-code", _AGENT_SESSION, "Swap the gripper camera for a global-shutter one", "research",
     "The gripper camera smears the tray edges when the arm moves at full speed, and calibration drifts "
     "afterwards. A global-shutter camera should fix both; it has to fit the current wrist mount."),
    (-6, "user", None, "Add a soft stop when the arm leaves the tray", "apply",
     "The arm can swing past the tray's edge when a grasp fails. A soft stop at the tray bounds keeps it off "
     "the bench."),
    (-5, "claude-code", _AGENT_SESSION, "Pick a wrist servo", "decide",
     "Two servos fit the wrist: a cheaper one with more backlash and a quieter one with less torque. It needs "
     "the person's call."),
)
_BACKLOG_NOTES = (
    (-30, "RAP1", "claude-code", _AGENT_SESSION, "The checklist is in the project notes, one step per line.",
     "done"),
    (-10, "RAP3", "claude-code", _AGENT_SESSION,
     "Measured at full speed: the smear starts above half speed, and the drift follows it.", None),
    (-8, "RAP2", "user", None, "One camera is enough once the shutter is fixed.", "dropped"),
    (-3, "RAP3", "user", None, "Hana Example has a spare global-shutter camera in the lab.", None),
    (-2, "RAP5", "user", None, "", "doing"),
)


def _write_scenario_backlog(bank_dir: Path, today: date) -> None:
    """Five items on the rover project and five notes (spec R-B26), through
    `backlog` — the writer every live path uses — each committed at once under
    whoever wrote it: the person's as `Backlog update` / `user/companion_app`
    (what the app commits), the agent's as `Agent write` / `mcp/claude-code`
    with its session (what MCP commits). A pinned `now` per write and
    `tz_name="UTC"`, like the rest of the scenario (R-PJB7), so no real clock
    reaches a file and the app fixture never moves. `populate` calls this
    BEFORE the scenario's events, whose two commits a test reads as the
    newest."""
    from datetime import datetime, time, timezone

    from api.services import backlog

    def at(offset: int) -> datetime:
        return datetime.combine(today + timedelta(days=offset), time(15, 0), tzinfo=timezone.utc)

    def commit(result: dict, author: str, session: str | None, action: str) -> None:
        paths = result.get("paths") or []
        if not paths:
            return
        if author == backlog.USER:
            message = backlog.commit_message(paths, action=action, subject="Backlog update",
                                             trigger="user/companion_app", day=str(today))
        else:
            message = backlog.commit_message(paths, action=action, subject="Agent write", trigger=f"mcp/{author}",
                                             day=str(today), author=author, session=session)
        _run_commit(bank_dir, message, paths)

    for offset, author, session, title, triage, description in _BACKLOG_ITEMS:
        commit(backlog.add_item(bank_dir, project="rover-arm-project", title=title, description=description,
                                triage=triage, author=author, session=session, now=at(offset), tz_name="UTC"),
               author, session, "created")
    for offset, item, author, session, text, status in _BACKLOG_NOTES:
        commit(backlog.add_note(bank_dir, project="rover-arm-project", item=item, note=text, status=status,
                                author=author, session=session, now=at(offset), tz_name="UTC"),
               author, session, "updated")
```

In `populate` (`:101-129`), call it right after `_commit_scenario(bank_dir, today, scenario)`:

```python
    _commit_scenario(bank_dir, today, scenario)
    _write_scenario_backlog(bank_dir, today)   # G150 R-B26 — before the events: a test reads their commits as newest
    _expire_scenario(bank_dir, today)
```

In `api/tests/_demo_scenario.py`: add `"backlog": "_write_scenario_backlog"` to `_STEPS`; give `demo(...)` a
`backlog: bool = True` parameter and add it to `wanted` (`{"events": events, "person": person, "followups":
followups, "backlog": backlog}`); and make `day_one` pass `backlog=False` too, with its docstring extended: "and no
backlog (G150): PJ-1's expectations predate it."

- [ ] **Step 6: Generate the fixture, then green.**
  `cd <worktree> && CICADA_WRITE_APP_FIXTURE=1 api/.venv/bin/python -m pytest api/tests/test_backlog_app_fixture.py
  -q -p no:cacheprovider` writes `app/CicadaApp/Tests/fixtures/backlog-demo.json`; read it once (five items, RAP3's two
  notes, no machine path). Then, without the variable:
  `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_backlog_router.py api/tests/test_backlog_import.py
  api/tests/test_backlog_app_fixture.py api/tests/test_projects_app_fixture.py api/tests/test_demo_bank.py
  api/tests/test_state_v3.py -q -p no:cacheprovider` passes — **`test_projects_app_fixture.py` must pass unchanged**:
  if `projects-demo.json` drifted, the backlog step touched an entity page or an episode, which R-B3 forbids; stop and
  find out why rather than regenerating it. Then the full backend suite: 0 failures.

- [ ] **Step 7: Commit.**

```bash
cd <worktree> && chmod +x scripts/import-backlog.sh && git add api/models/schemas.py api/routers/backlog.py \
  api/main.py api/services/backlog_import.py scripts/import-backlog.sh api/services/demo_bank.py \
  api/tests/_demo_scenario.py api/tests/test_backlog_router.py api/tests/test_backlog_import.py \
  api/tests/test_backlog_app_fixture.py app/CicadaApp/Tests/fixtures/backlog-demo.json \
  && git commit -m "feat(backlog): the person's routes, the G-row importer, the demo's backlog (G150 R-B7…R-B26)

GET /projects/{id}/backlog and GET /backlog/{project}/{item} (ETag over the
backlog and entities components), the person's add, note and edit (Backlog
update, Cicada-Author: user, 409 while Sleep runs), and the importer's live
path. backlog_import reads G-row tables and ### G<n> sections, keeps ids and
states, skips an id already filed (a second run changes nothing), and
scripts/import-backlog.sh runs it on a named bank. The demo files five items on
its rover project; backlog-demo.json is its wire, pinned for the app.

<attribution lines>"
```

---

### Task 3: Agents — three MCP tools, the contract, `_state.md` v4, `cicada_project` (G150 R-B6, R-B8, R-B12, R-B13, R-B16, R-B17; brief R3–R5)

The agent's side: `cicada_backlog`, `cicada_add_backlog_item`, `cicada_add_backlog_note`, local and remote, and the
primer that tells an agent what to do when the person says "put it in the backlog". After this task an agent can
file, note and read; the app does not show the backlog yet.

**Files:**
- Modify: `api/services/mcp_tools.py` — three tool bodies after `note_progress` (`:967-1117`); `project`
  (`:891-925`) passes the open items
- Modify: `mcp/server.py` — three schemas before `TOOLS` closes (`:621`), dispatch in `handle_tool` (`:768-848`),
  three handlers after `handle_note_progress` (`:919-925`)
- Modify: `api/remote/catalog.py:29-55`, `api/remote/tools.py` (after `cicada_note_progress`, `:200-223`),
  `api/remote/runtime.py:170-200`
- Modify: `api/services/handshake.py` — versions (`:56`, `:71`), `_remote_contract` (`:98-144`), `_CONTRACT` item 3
  and 7 (`:205-226`), the Current row (`:353-369`)
- Modify: `api/services/state_dictionary.py` — `SCHEMA_VERSION` (`:81`), `INPUT_COMPONENTS` (`:95`), the project rows
  (`:490-512`), `_cursor` (`:590-599`)
- Modify: `api/services/project_text.py` — `render` (`:258-296`)
- Test: `api/tests/test_backlog_tools.py` (new); pins moved in `api/tests/test_demo_capture.py:245-256`,
  `api/tests/test_handshake.py:55-56`, `api/tests/test_handshake_r12.py:89`, `api/tests/test_state_v3.py:15`,
  `api/tests/test_state_dictionary.py:33, :251`, `api/tests/test_state_wiring.py:150` (the last three pin
  `schema_version == 3` too — found by running the full suite against this plan's code)

**Interfaces:**
- Produces `mcp_tools.backlog(ctx, project, status=None, item=None)`, `mcp_tools.add_backlog_item(ctx, project,
  title, description, triage=None, paid=None)`, `mcp_tools.add_backlog_note(ctx, item, note, status=None)`,
  `mcp_tools.BACKLOG_SLEEPING`, `mcp_tools.PERSONS_WORDS`; the stdio and remote schemas; `_state.md` rows'
  `backlog_open`; `project_text.render(..., backlog=(), can_backlog=False)`.
- Consumes Task 1's `backlog.*`, `ToolContext`, `agent_commits.commit_write`, `telemetry.record` /
  `record_read`.

- [ ] **Step 1: Failing tests.** Create `api/tests/test_backlog_tools.py`:

```python
"""G150 — agents file, note and read a project's backlog over MCP, locally and remotely (R-B6, R-B8, R-B12,
R-B13, R-B16, R-B17). Synthetic only."""
import subprocess

import pytest

from _stdio_server import stdio_server
from _synthetic_bank import _bank, _ok_repo, _settings
from api.remote import catalog
from api.remote import tools as remote_tools
from api.services import backlog, bank_index, handshake, mcp_tools, state_dictionary


@pytest.fixture
def bank(tmp_path, monkeypatch):
    memory = _bank(tmp_path)                                      # a git bank: every write commits
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))    # the state file's reads never reach ~/.cicada
    monkeypatch.setattr(handshake, "local_timezone", lambda: "UTC")
    bank_index.invalidate()
    return memory


def _ctx(bank, scopes=None):
    if scopes is None:
        return mcp_tools.ToolContext(memory_path=lambda: bank, session_id="ses_test", harness="claude-code")
    return mcp_tools.ToolContext(memory_path=lambda: bank, session_id="rc_abcd1234_x", harness="claude-web",
                                 connector_id="abcd1234", available=catalog.tool_names_for(scopes),
                                 raw_excerpts="sources" in scopes, read_surface="remote")


def _git(bank, *args):
    return subprocess.run(["git", *args], cwd=bank, capture_output=True, text=True, check=True).stdout


def test_an_agent_files_an_item_notes_it_and_reads_it_back(bank):
    ctx = _ctx(bank)
    reply = mcp_tools.add_backlog_item(ctx, "alpha-project", "Cache the timeline", "Opening a big project is slow.",
                                       "apply")
    assert reply.startswith("Added AP1 to alpha-project's backlog: Cache the timeline (open).")
    assert 'cicada_add_backlog_note(item="alpha-project/AP1", note)' in reply
    log = _git(bank, "log", "-1", "--format=%B")
    assert log.startswith("Agent write ") and "Cicada-Author: claude-code" in log and "Cicada-Session: ses_test" in log
    assert "backlog/alpha-project/AP1.md: created (source: n/a, trigger: mcp/claude-code)" in log
    assert _git(bank, "show", "--name-only", "--format=", "HEAD").split() == ["backlog/alpha-project/AP1.md"]
    assert mcp_tools.add_backlog_note(ctx, "AP1", "Found the slow path.", "doing") == \
        "Noted on AP1 (Cache the timeline) — now doing."
    listed = mcp_tools.backlog(ctx, "Alpha Project")
    assert listed.splitlines()[0] == "Alpha Project backlog — 0 open · 1 doing · 0 done · 0 dropped"
    assert "- AP1 · Cache the timeline — doing · apply · last note" in listed and "by Claude Code" in listed
    full = mcp_tools.backlog(ctx, "alpha-project", item="AP1")
    assert "Description:\nOpening a big project is slow." in full
    assert "· Claude Code: Found the slow path.\n\nMoved from open to doing." in full


def test_one_row_per_idea_the_second_filing_points_at_the_first(bank):
    ctx = _ctx(bank)
    mcp_tools.add_backlog_item(ctx, "alpha-project", "Cache the timeline", "Slow.")
    head = _git(bank, "rev-parse", "HEAD")
    reply = mcp_tools.add_backlog_item(ctx, "alpha-project", "cache the  timeline", "Still slow.")
    assert reply.startswith("NOT added — AP1 already holds this idea") and "cicada_add_backlog_note" in reply
    assert _git(bank, "rev-parse", "HEAD") == head


def test_refusals_are_one_line_and_write_nothing(bank, monkeypatch):
    ctx = _ctx(bank)
    assert "Nothing was added" in mcp_tools.add_backlog_item(ctx, "alpha-project", "X", "   ")
    assert mcp_tools.add_backlog_item(ctx, "bob-example", "X", "Why.").startswith(
        "Not added: bob-example is a person")
    assert mcp_tools.add_backlog_note(ctx, "ZZ9", "x").startswith("Not noted: no backlog item ZZ9")
    assert mcp_tools.backlog(ctx, "alpha-project", status="someday").startswith("'someday' isn't a status")
    monkeypatch.setattr(mcp_tools, "_backend_sleep_running", lambda url, headers: True)
    assert mcp_tools.add_backlog_item(ctx, "alpha-project", "X", "Why.") == mcp_tools.BACKLOG_SLEEPING
    assert not (bank / "backlog").exists()


def test_a_remote_app_writes_as_itself_and_without_sources_never_reads_the_persons_words(bank):
    backlog.add_item(bank, project="alpha-project", title="Mine", description="My own reasoning.", author="user")
    backlog.add_note(bank, project="alpha-project", item="AP1", note="My own note.", author="user")
    remote = _ctx(bank, {"search", "read", "record"})
    assert mcp_tools.add_backlog_item(remote, "alpha-project", "Theirs", "An agent's reasoning.").startswith("Added AP2")
    log = _git(bank, "log", "-1", "--format=%B")
    assert log.startswith("Remote write ") and "Cicada-Author: claude-web" in log
    assert "trigger: remote/claude-web" in log and "Cicada-Session: rc_abcd1234_x" in log
    shown = mcp_tools.backlog(remote, "alpha-project", item="AP1")
    assert "My own reasoning." not in shown and "My own note." not in shown and mcp_tools.PERSONS_WORDS in shown
    assert "An agent's reasoning." in mcp_tools.backlog(remote, "alpha-project", item="AP2")
    assert "My own note." in mcp_tools.backlog(_ctx(bank, {"read", "sources"}), "alpha-project", item="AP1")
    assert "cicada_add_backlog_note" not in mcp_tools.backlog(_ctx(bank, {"read"}), "alpha-project")


def test_the_tools_are_classified_once_and_their_schemas_carry_the_contracts_arguments():
    assert catalog.TOOL_SCOPE["cicada_backlog"] == "read" and "cicada_backlog" in catalog.READ_TOOLS
    for tool in ("cicada_add_backlog_item", "cicada_add_backlog_note"):
        assert catalog.TOOL_SCOPE[tool] == "record" and tool in catalog.WRITE_TOOLS
    stdio = {t["name"]: t for t in stdio_server().TOOLS}
    assert stdio["cicada_add_backlog_item"]["inputSchema"]["required"] == ["project", "title", "description"]
    assert stdio["cicada_add_backlog_note"]["inputSchema"]["required"] == ["item", "note"]
    assert set(remote_tools.REMOTE_TOOLS["cicada_backlog"]["inputSchema"]["properties"]) == {
        "project", "status", "item", "conversation"}


def test_the_stdio_server_dispatches_the_three_tools(bank, monkeypatch):
    server = stdio_server()
    monkeypatch.setattr(server, "get_memory_path", lambda: bank)
    assert server.handle_tool("cicada_add_backlog_item", {"project": "alpha-project", "title": "X",
                                                          "description": "Why."}).startswith("Added AP1")
    assert server.handle_tool("cicada_add_backlog_note", {"item": "AP1", "note": "Found."}).startswith("Noted on AP1")
    assert server.handle_tool("cicada_backlog", {"project": "alpha-project"}).startswith("Alpha Project backlog")


def test_the_primer_says_what_to_do_and_counts_open_items(bank):
    assert (handshake.CONTRACT_VERSION, handshake.REMOTE_CONTRACT_VERSION) == (7, 5)
    backlog.add_item(bank, project="alpha-project", title="One", author="user")
    backlog.add_item(bank, project="alpha-project", title="Two", author="user")
    state_dictionary.refresh(bank, _settings(bank), force=True, repo_resolver=_ok_repo)
    st = state_dictionary.read_state(bank)
    assert st["schema_version"] == 4
    rows = {p["id"]: p for p in st["projects"]}
    assert rows["alpha-project"]["backlog_open"] == 2
    assert all("backlog_open" not in p for pid, p in rows.items() if pid != "alpha-project")
    text = handshake.build(st, variant="claude-code", bank="memory", tz="UTC")
    assert "`cicada_add_backlog_item(project, title, description)`" in text and "never a second item" in text
    assert "`backlog/`" in text and " · backlog: 2 open" in text
    assert len(text) // 4 <= handshake.MAX_TOKENS
    record_only = handshake.build_remote(st, tools=catalog.tool_names_for({"record"}), bank="memory")
    assert "cicada_add_backlog_item(" in record_only and " · backlog: " not in record_only   # G140's gate


def test_a_backlog_write_moves_the_state_files_inputs(bank):
    before = state_dictionary.inputs_version(bank)
    backlog.add_item(bank, project="alpha-project", title="One", author="user")
    assert state_dictionary.inputs_version(bank) != before


def test_cicada_project_lists_the_open_items_and_names_the_tool_only_when_held(tmp_path, monkeypatch):
    from _demo_scenario import T, demo

    b = demo(tmp_path)
    monkeypatch.setattr(handshake, "local_timezone", lambda: "UTC")
    monkeypatch.setattr(mcp_tools, "_today_in", lambda tz: T)
    local = mcp_tools.ToolContext(memory_path=lambda: b, session_id="ses_test", harness="claude-code")
    assert ("Backlog: 3 open — RAP5 Pick a wrist servo [decide] (doing); RAP3 Swap the gripper camera for a "
            "global-shutter one [research]; RAP4 Add a soft stop when the arm leaves the tray [apply] — "
            "cicada_backlog(project) lists them all") in mcp_tools.project(local, "rover-arm-project")
    narrow = mcp_tools.ToolContext(memory_path=lambda: b, session_id="rc_x", harness="claude-web",
                                   connector_id="abcd1234", available=frozenset({"cicada_project"}),
                                   raw_excerpts=False, read_surface="remote")
    out = mcp_tools.project(narrow, "rover-arm-project")
    assert "Backlog: 3 open" in out and "cicada_backlog(" not in out
```

Move the pins this task changes on purpose:
- `api/tests/test_demo_capture.py:245-256` — add to `WRITES`:
  `"cicada_add_backlog_item": lambda ctx: mcp_tools.add_backlog_item(ctx, "alpha-project", "Cache it", "Slow."),`
  and `"cicada_add_backlog_note": lambda ctx: mcp_tools.add_backlog_note(ctx, "AP1", "Found it."),`.
- `api/tests/test_handshake.py:55-56` — `assert handshake.CONTRACT_VERSION == 7, ("G140 named its tools (3), bridge
  lines joined (G138, 4), G141 named cicada_project (5) and cicada_note_progress (6), G150 the backlog tools (7)")`.
- `api/tests/test_handshake_r12.py:89` — the parametrize list becomes `["cicada_project", "cicada_note_progress",
  "cicada_backlog", "cicada_add_backlog_item", "cicada_add_backlog_note"]`, and its docstring adds "and G150's three
  backlog tools".
- `api/tests/test_state_v3.py:15` — `assert st["schema_version"] == state_dictionary.SCHEMA_VERSION   # v4 (G150)
  only adds backlog_open, and this bank has no backlog`.
- `api/tests/test_state_dictionary.py:33` — `assert fm["type"] == "state" and fm["schema_version"] ==
  state_dictionary.SCHEMA_VERSION`; `:251` — `assert fm["schema_version"] == state_dictionary.SCHEMA_VERSION`.
- `api/tests/test_state_wiring.py:150` — `assert data["schema_version"] == state_dictionary.SCHEMA_VERSION and
  data["bank"] == "memory"` (`state_dictionary` is already imported there).

Run: `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_backlog_tools.py
api/tests/test_demo_capture.py api/tests/test_handshake.py api/tests/test_handshake_r12.py -q -p no:cacheprovider`
→ `AttributeError: module 'api.services.mcp_tools' has no attribute 'add_backlog_item'` and the version pins fail.
That is the red.

- [ ] **Step 2: The tool bodies.** In `api/services/mcp_tools.py`, after `note_progress` (it ends at `:1117`, before
  `def write_claim(`), add:

```python
# --------------------------------------------------------------------------- #
# G150 — a project's backlog (R-B6, R-B7, R-B8, R-B12, R-B13)
# --------------------------------------------------------------------------- #

BACKLOG_ROWS = 25
BACKLOG_SLEEPING = "Sleep is consolidating memory right now — try again in a minute. Nothing was written."
# R-B12: R-R22's rail — a remote connection without `sources` never reads the
# person's own words; it is told they exist.
PERSONS_WORDS = "(the person's own words — this connection can't read them)"


def _backlog_words(ctx: ToolContext, by: str, text: str) -> str:
    return text if ctx.raw_excerpts or by != "user" else PERSONS_WORDS


def _backlog_row(item, tz: str) -> str:
    from api.services import backlog as store

    bits = [item.status] + ([item.triage] if item.triage else []) + (["paid AI"] if item.paid else [])
    last = store.local_day(item.last_note_at, tz)
    said = (f"last note {last} by {store.who_label(item.last_note_by)}" if last
            else f"added {item.created} by {store.who_label(item.added_by)}")
    return f"- {item.id} · {item.title} — {' · '.join(bits)} · {said}"


def _backlog_item_text(ctx: ToolContext, it) -> str:
    from api.services import backlog as store

    head = f"{it.id} · {it.title} — {it.status}" + (f" · {it.triage}" if it.triage else "") \
        + (" · paid AI" if it.paid else "")
    lines = [head, f"On {it.project}'s backlog, added {it.created} by {store.who_label(it.added_by)}.", "",
             "Description:", _backlog_words(ctx, it.added_by, it.description) if it.description else "(none)"]
    if it.links:
        lines.append("Links: " + ", ".join(f"{link['kind']} {link['ref']}" for link in it.links))
    lines += ["", f"Notes ({len(it.notes)}):" if it.notes else "Notes: none yet."]
    lines += [f"- {n.day} · {n.who}: {_backlog_words(ctx, store.author_of(n), n.text)}" for n in it.notes]
    if ctx.can("cicada_add_backlog_note"):
        lines += ["", f"Add what you find with cicada_add_backlog_note(item=\"{it.project}/{it.id}\", note)."]
    return "\n".join(lines)


def _commit_backlog(ctx: ToolContext, memory_path: Path, paths: list[str], action: str, item) -> None:
    """G135 R-R11 for a backlog write (R-B7): the item's own file, its own
    commit under the harness, the conversation as `Cicada-Session:`, and one
    ids-and-enums `agentic_write` ledger row — never a title or a note."""
    from api.services import telemetry

    refs = {"entity_id": item.project, "item_id": item.id, "action": f"backlog_{action}",
            "session_id": ctx.session_id, "harness": ctx.harness, "client_name": ctx.client_name,
            "client_version": ctx.client_version}
    if ctx.is_remote:
        refs["connector_id"] = ctx.connector_id
    telemetry.record(telemetry.UsageEvent(
        kind="agentic_write", stage="driver", connection="session",
        engine="mcp-remote" if ctx.is_remote else "mcp-client", model=None, bank=memory_path.name,
        billing="subscription", invocations=1, refs=refs))
    agent_commits.commit_write(
        memory_path, subject=ctx.commit_subject,
        lines=[f"{p}: {action} (source: n/a, trigger: {ctx.trigger})" for p in paths],
        paths=paths, author=ctx.author, session=ctx.session_id)


def backlog(ctx: ToolContext, project: str, status=None, item=None) -> str:
    """`cicada_backlog` (G150, R-B13): a project's backlog as text an agent can
    act on — or, with `item`, one item in full (its reasoning and every signed
    note), because "add a note, never a second item" starts with reading the
    row. Engine-free; writes nothing but an ids-only `read` ledger row."""
    from api.services import backlog as store
    from api.services import handshake, telemetry

    memory_path = ctx.memory_path()
    tz = handshake.local_timezone() or "UTC"
    ref = (project or "").strip()
    if item:
        got = store.resolve_item(memory_path, str(item), ref or None)
        if isinstance(got, dict):
            return f"{got['error'].split(';')[0]}."
        stem, iid = got
        it = store.get_item(memory_path, stem, iid)
        if it is None:
            return f"No {iid} on {stem}'s backlog."
        telemetry.record_read(stem, surface=f"{ctx.read_surface}-backlog", bank=memory_path.name)
        return _backlog_item_text(ctx, it)
    if not ref:
        return "project is required — a project's id or name."
    got = store.project_page(memory_path, ref)
    if isinstance(got, dict):
        return f"{got['error'].split(';')[0]}."
    stem, fm = got
    wanted = (status or "").strip().lower() or None
    if wanted not in (None, "all", *store.STATUSES):
        return f"'{status}' isn't a status — use open, doing, done, dropped or all."
    items = store.list_items(memory_path, stem)
    c = store.counts(items)
    if wanted is None:
        shown = [i for i in items if i.status in store.OPEN_STATUSES]
    else:
        shown = [i for i in items if wanted == "all" or i.status == wanted]
    lines = [f"{fm.get('name') or stem} backlog — " + " · ".join(f"{c[s]} {s}" for s in store.STATUSES)]
    if not items:
        lines.append("Nothing on it yet.")
    elif not shown:
        lines.append("No open or doing items." if wanted is None else f"No {wanted} items.")
    lines += [_backlog_row(i, tz) for i in shown[:BACKLOG_ROWS]]
    if len(shown) > BACKLOG_ROWS:
        lines.append(f"…and {len(shown) - BACKLOG_ROWS} more — pass status to narrow.")
    if shown:
        lines.append(f"Read one in full with cicada_backlog(project, item=\"{shown[0].id}\").")
    if ctx.can("cicada_add_backlog_note"):
        lines.append("Add findings to an item with cicada_add_backlog_note(item, note) — never a second item "
                     "for the same idea.")
    telemetry.record_read(stem, surface=f"{ctx.read_surface}-backlog", bank=memory_path.name)
    return "\n".join(lines)


def add_backlog_item(ctx: ToolContext, project: str, title: str, description: str, triage=None, paid=None) -> str:
    """`cicada_add_backlog_item` (G150, R-B13): the person asked for something
    to go on a project's backlog. The author is the harness — never the
    person, remote or not (G135 R-R11) — and the conversation is kept so a
    note can be joined to its turn at read (R-B6). Refused, each in one line
    and writing nothing: in a demo bank, without a reasoning, while Sleep runs
    (R-B8), and when an open item already holds the idea (R-B9)."""
    from api.services import backlog as store

    memory_path = ctx.memory_path()
    if (refusal := _demo_refusal(memory_path)) is not None:
        return refusal
    if not str(description or "").strip():
        return ("Give the reasoning as the description — the problem, the evidence, what a fix must respect. "
                "Nothing was added.")
    if ctx.sleep_running():
        return BACKLOG_SLEEPING
    result = store.add_item(memory_path, project=str(project or ""), title=str(title or ""),
                            description=str(description), triage=triage, paid=bool(paid), author=ctx.author,
                            session=ctx.session_id)
    action = result.get("action")
    if action == "duplicate":
        address = f"{result['project']}/{result['item_id']}"
        tail = (f" Add what you found to it with cicada_add_backlog_note(item=\"{address}\", note)."
                if ctx.can("cicada_add_backlog_note") else "")
        return f"NOT added — {result['item_id']} already holds this idea on {result['project']}'s backlog.{tail}"
    if action != "added":
        return f"Not added: {result.get('error') or 'unknown error'}."
    item = result["item"]
    _commit_backlog(ctx, memory_path, result["paths"], "created", item)
    tail = (f" Add later findings to it with cicada_add_backlog_note(item=\"{item.project}/{item.id}\", note)."
            if ctx.can("cicada_add_backlog_note") else "")
    return f"Added {item.id} to {item.project}'s backlog: {item.title} (open).{tail}"


def add_backlog_note(ctx: ToolContext, item: str, note: str, status=None) -> str:
    """`cicada_add_backlog_note` (G150): what an agent learned about an item —
    appended and signed, never overwriting (R-B4) — optionally moving it
    (R-B5). `item` is `RAP3` or `<project>/RAP3`; a bare id two projects share
    is refused with both addresses (R-B13)."""
    from api.services import backlog as store

    memory_path = ctx.memory_path()
    if (refusal := _demo_refusal(memory_path)) is not None:
        return refusal
    got = store.resolve_item(memory_path, str(item or ""))
    if isinstance(got, dict):
        return f"Not noted: {got['error']}."
    stem, iid = got
    if ctx.sleep_running():
        return BACKLOG_SLEEPING
    move = (str(status).strip().lower() or None) if status else None
    result = store.add_note(memory_path, project=stem, item=iid, note=str(note or ""), status=move,
                            author=ctx.author, session=ctx.session_id)
    action = result.get("action")
    if action == "unchanged":
        return f"{iid} is already {result['item'].status}; nothing was written."
    if action != "updated":
        return f"Not noted: {result.get('error') or 'unknown error'}."
    it = result["item"]
    _commit_backlog(ctx, memory_path, result["paths"], "updated", it)
    return f"Noted on {it.id} ({it.title}) — now {it.status}."
```

In `project` (`:891-925`), replace its final `return project_text.render(...)` with:

```python
    # G150 (R-B16): the open backlog, from frontmatter alone — never a body.
    from api.services import backlog as backlog_store

    open_items = [i for i in backlog_store.list_items(memory_path, timeline.project.id)
                  if i.status in backlog_store.OPEN_STATUSES]
    return project_text.render(timeline, state, memory_path=memory_path, today=today, raw=ctx.raw_excerpts,
                               can_note=ctx.can("cicada_note_progress"), can_detail=ctx.can("cicada_recall_detail"),
                               backlog=open_items, can_backlog=ctx.can("cicada_backlog"))
```

In `api/services/project_text.py`, give `render` two keyword parameters (`backlog=(), can_backlog: bool = False`,
after `can_detail`), add the helper above it, and append the line just before `around = _around_line(timeline)`:

```python
BACKLOG_IN_REPLY = 5


def _backlog_line(items, can_backlog: bool) -> str | None:
    """G150 (R-B16): the project's open backlog items, most recently touched
    first, at most five by title — and the tool that lists them all, named
    only for a caller that holds it (R12 for tool output)."""
    items = list(items or ())
    if not items:
        return None
    shown = ["{} {}".format(i.id, i.title) + (f" [{i.triage}]" if i.triage else "")
             + (" (doing)" if i.status == "doing" else "") for i in items[:BACKLOG_IN_REPLY]]
    line = f"Backlog: {len(items)} open — " + "; ".join(shown)
    if len(items) > BACKLOG_IN_REPLY:
        line += f"; and {len(items) - BACKLOG_IN_REPLY} more"
    return line + (" — cicada_backlog(project) lists them all" if can_backlog else "")
```

```python
    backlog_line = _backlog_line(backlog, can_backlog)
    if backlog_line:
        lines.append(backlog_line)
    around = _around_line(timeline)
```

- [ ] **Step 3: The stdio server.** In `mcp/server.py`, add three entries at the end of `TOOLS` (before `]` at `:621`):

```python
    {
        # G150 R-B13: `read` scope remotely; `item` reads one row in full.
        "name": "cicada_backlog",
        "description": "A project's backlog: the tasks and ideas the person asked to keep for later, each with its id, status (open, doing, done, dropped), triage and latest note. Pass `item` to read one in full — its description (the reasoning) and every note, signed by who wrote it. Read an item before adding a note to it.",
        "inputSchema": {"type": "object", "required": ["project"], "properties": {
            "project": {"type": "string", "description": "A project's id or name."},
            "status": {"type": "string", "enum": ["open", "doing", "done", "dropped", "all"],
                       "description": "Optional: which items to list. Default: open and doing."},
            "item": {"type": "string", "description": "Optional: one item's id (e.g. 'RAP3') to read in full."}}},
    },
    {
        # G150: a write, `record` scope remotely; the harness is the author, never the person.
        "name": "cicada_add_backlog_item",
        "description": "Put something on a project's backlog when the person asks you to ('put it in the backlog', 'keep this for later', 'add a task'). The title is the brief task in one line; the description is the reasoning — the problem, the evidence, and what any fix must respect. One item per idea: if it is already there, add a note to it with cicada_add_backlog_note instead.",
        "inputSchema": {"type": "object", "required": ["project", "title", "description"], "properties": {
            "project": {"type": "string", "description": "The project page (id or name)."},
            "title": {"type": "string", "description": "The brief task, one line."},
            "description": {"type": "string", "description": "The reasoning: the problem, the evidence, the constraint a fix must respect."},
            "triage": {"type": "string", "enum": ["apply", "research", "decide"],
                       "description": "Optional: apply (buildable now), research (needs investigation) or decide (needs the person's call)."},
            "paid": {"type": "boolean", "description": "Optional: true when doing it needs paid AI usage."}}},
    },
    {
        "name": "cicada_add_backlog_note",
        "description": "Add what you learned to an existing backlog item — a finding, a measurement, a decision — and optionally move it (doing, done, dropped). Notes are appended and signed; nothing is overwritten. Use this rather than filing a second item for the same idea.",
        "inputSchema": {"type": "object", "required": ["item", "note"], "properties": {
            "item": {"type": "string", "description": "The item's id (e.g. 'RAP3'), or '<project>/<id>' when two projects share a prefix."},
            "note": {"type": "string", "description": "What you found, in a few sentences."},
            "status": {"type": "string", "enum": ["open", "doing", "done", "dropped"],
                       "description": "Optional: move the item as you note it."}}},
    },
```

In `handle_tool` (`:768-848`), after the `cicada_note_progress` branch:

```python
    elif name == "cicada_backlog":
        return handle_backlog(arguments)
    elif name == "cicada_add_backlog_item":
        return handle_add_backlog_item(arguments)
    elif name == "cicada_add_backlog_note":
        return handle_add_backlog_note(arguments)
```

After `handle_note_progress` (`:919-925`):

```python
def handle_backlog(arguments: dict) -> str:
    """`cicada_backlog` (G150) — read-only, engine-free."""
    return mcp_tools.backlog(_ctx(), str(arguments.get("project") or ""), arguments.get("status"),
                             arguments.get("item"))


def handle_add_backlog_item(arguments: dict) -> str:
    """`cicada_add_backlog_item` (G150) — the person asked for it to go on the backlog."""
    return mcp_tools.add_backlog_item(_ctx(), str(arguments.get("project") or ""), str(arguments.get("title") or ""),
                                      str(arguments.get("description") or ""), arguments.get("triage"),
                                      arguments.get("paid"))


def handle_add_backlog_note(arguments: dict) -> str:
    """`cicada_add_backlog_note` (G150) — a finding on an item already filed."""
    return mcp_tools.add_backlog_note(_ctx(), str(arguments.get("item") or ""), str(arguments.get("note") or ""),
                                      arguments.get("status"))
```

- [ ] **Step 4: Remote.** `api/remote/catalog.py` — in `TOOL_SCOPE`, add `"cicada_backlog": "read",   # G150 R-B13`
  after `cicada_project`, and `"cicada_add_backlog_item": "record",` / `"cicada_add_backlog_note": "record",   # G150:
  the harness writes, never the person` after `cicada_note_progress`; add the two to `WRITE_TOOLS` and
  `cicada_backlog` to `READ_TOOLS`. `api/remote/runtime.py` — in `_DISPATCH`, after `cicada_note_progress`:

```python
    "cicada_backlog": lambda c, a: mcp_tools.backlog(c, str(a.get("project") or ""), a.get("status"), a.get("item")),
    "cicada_add_backlog_item": lambda c, a: mcp_tools.add_backlog_item(
        c, str(a.get("project") or ""), str(a.get("title") or ""), str(a.get("description") or ""),
        a.get("triage"), a.get("paid")),
    "cicada_add_backlog_note": lambda c, a: mcp_tools.add_backlog_note(
        c, str(a.get("item") or ""), str(a.get("note") or ""), a.get("status")),
```

`api/remote/tools.py` — after the remote `cicada_note_progress` (`:200-223`):

```python
    # G150 (R-B13). The read names no write tool — it is `read` scope, and a
    # connection may hold only that (G75 R12); the two writes are `record`.
    _tool("cicada_backlog",
          "A project's backlog: the tasks and ideas the person keeps for later, each with its id, status (open, "
          "doing, done, dropped), triage and latest note. Pass `item` to read one in full — its description and "
          "every note, signed by who wrote it.",
          {"project": {"type": "string", "description": "A project's id or name."},
           "status": {"type": "string", "enum": ["open", "doing", "done", "dropped", "all"],
                      "description": "Optional: which items to list. Default: open and doing."},
           "item": {"type": "string", "description": "Optional: one item's id (e.g. 'RAP3') to read in full."}},
          ("project",), read_only=True),
    _tool("cicada_add_backlog_item",
          "Put something on one of the person's project backlogs when they ask ('put it in the backlog', 'keep this "
          "for later'). The title is the brief task in one line; the description is the reasoning — the problem, "
          "the evidence, what a fix must respect. One item per idea: if it is already there, add a note to it with "
          "cicada_add_backlog_note instead.",
          {"project": {"type": "string", "description": "The project page (id or name)."},
           "title": {"type": "string", "description": "The brief task, one line."},
           "description": {"type": "string", "description": "The reasoning: the problem, the evidence, the "
                                                            "constraint a fix must respect."},
           "triage": {"type": "string", "enum": ["apply", "research", "decide"],
                      "description": "Optional: apply, research or decide."},
           "paid": {"type": "boolean", "description": "Optional: true when doing it needs paid AI usage."}},
          ("project", "title", "description"), read_only=False),
    _tool("cicada_add_backlog_note",
          "Add what you learned to an existing backlog item — a finding, a measurement, a decision — and optionally "
          "move it (doing, done, dropped). Notes are appended and signed with this app; nothing is overwritten.",
          {"item": {"type": "string", "description": "The item's id (e.g. 'RAP3'), or '<project>/<id>'."},
           "note": {"type": "string", "description": "What you found, in a few sentences."},
           "status": {"type": "string", "enum": ["open", "doing", "done", "dropped"],
                      "description": "Optional: move the item as you note it."}},
          ("item", "note"), read_only=False),
```

- [ ] **Step 5: The primer and `_state.md`.** In `api/services/handshake.py`:
  - After the `# 6: G141 PJ-3a …` comment: `# 7: G150 — item 3 names cicada_add_backlog_item, cicada_add_backlog_note
    and` / `# cicada_backlog; item 7 adds backlog/ to what is never edited directly.` and `CONTRACT_VERSION = 7`.
  - After `# 4: G141 PJ-3a …` on the remote side: `# 5: G150 — cicada_backlog among the reads; the backlog sentence
    when the` / `# connection holds cicada_add_backlog_item.` and `REMOTE_CONTRACT_VERSION = 5`.
  - `_CONTRACT` item 3: replace the literal line `"status, evidence)`.\n"` with

```python
    "status, evidence)`. When the person asks to put something in the backlog (or to keep it for later), file it "
    "with `cicada_add_backlog_item(project, title, description)` — the brief task as the title, the reasoning as the "
    "description; later findings go on that item with `cicada_add_backlog_note(item, note)`, never a second item; "
    "`cicada_backlog(project)` lists what is open.\n"
```

  - `_CONTRACT` item 7: "Never edit `entities/`, `hubs/` or `_index.md` directly" → "Never edit `entities/`, `hubs/`,
    `backlog/` or `_index.md` directly".
  - `_remote_contract` — add `("cicada_backlog", "`cicada_backlog(project)` for a project's backlog"),` as the last
    entry of the `reads` tuple, and after the `cicada_note_progress` block:

```python
    if "cicada_add_backlog_item" in tools:
        # G150: named only where the tool exists (R12); the note tool shares
        # its `record` scope, so the two always travel together.
        items.append("When the person asks you to put something in the backlog, file it with "
                     "`cicada_add_backlog_item(project, title, description)` — the brief task as the title, the "
                     "reasoning as the description; later findings go on that item with "
                     "`cicada_add_backlog_note(item, note)`, never a second item.")
```

  - `_now_block`'s project loop, right after the `next` cursor line:

```python
        # G150 (R-B16): the open backlog count rides the same gate as now/next.
        if p.get("backlog_open") and personal:
            cursor += f" · backlog: {p['backlog_open']} open"
```

  In `api/services/state_dictionary.py`:
  - `# 4: G150 — a project row carries backlog_open (items open or doing) when it` / `# has any; a bank with no
    backlog renders as v3 did apart from this number.` and `SCHEMA_VERSION = 4`.
  - `INPUT_COMPONENTS = ("entities", "inbox", "episodes", "bank", "backlog")`, the comment above gaining "`backlog`
    (G150): a new item or a move re-renders a project's count".
  - In `build`, just before `projects = []`:

```python
    # G150 (R-B16): one frontmatter pass over `backlog/` (bank_index's cache),
    # never a body.
    from api.services import backlog as backlog_store

    try:
        open_backlog = backlog_store.open_counts(memory_path)
    except Exception as exc:  # noqa: BLE001 — a count is never worth a failed state file
        logger.warning(f"_state.md backlog counts skipped: {type(exc).__name__}")
        open_backlog = {}
```

    and inside the project loop, after `if next_row: row["next"] = next_row`:

```python
        if open_backlog.get(f.stem):
            row["backlog_open"] = open_backlog[f.stem]
```

  - `_cursor`: after the `next` bit, `if p.get("backlog_open"): bits.append(f"backlog: {p['backlog_open']} open")`.

- [ ] **Step 6: Green.** `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_backlog_tools.py
  api/tests/test_demo_capture.py api/tests/test_handshake.py api/tests/test_handshake_r12.py
  api/tests/test_remote_tools.py api/tests/test_state_v3.py api/tests/test_state_dictionary.py
  api/tests/test_state_wiring.py api/tests/test_cicada_project.py api/tests/test_mcp_stdio_golden.py -q -p
  no:cacheprovider` passes. Then the full backend suite: 0 failures.

- [ ] **Step 7: Commit.**

```bash
cd <worktree> && git add api/services/mcp_tools.py mcp/server.py api/remote/catalog.py api/remote/tools.py \
  api/remote/runtime.py api/services/handshake.py api/services/state_dictionary.py api/services/project_text.py \
  api/tests/test_backlog_tools.py api/tests/test_demo_capture.py api/tests/test_handshake.py \
  api/tests/test_handshake_r12.py api/tests/test_state_v3.py api/tests/test_state_dictionary.py \
  api/tests/test_state_wiring.py \
  && git commit -m "feat(backlog): agents file, note and read the backlog; the primer says when (G150 R-B12…R-B17)

cicada_add_backlog_item and cicada_add_backlog_note (record scope remotely)
write as the harness with the conversation as Cicada-Session, refuse while
Sleep runs and in a demo bank, and point a second filing of an open idea at the
first. cicada_backlog (read) lists a project's items or reads one in full; a
remote connection without sources is told the person's own words exist, never
shown them. Contract item 3 says what to do when the person says 'put it in the
backlog' (CONTRACT_VERSION 7, remote 5); _state.md v4 counts each project's
open items for the Current line; cicada_project lists the top five.

<attribution lines>"
```

---

### Task 4: The app's wire, cache and writes — no view yet (G150 R-B18, R-B19's decisions, R-B22; DR-21, DR-54, DR-58, DR-59)

Everything the Backlog section and the item card have to *decide* becomes tested Swift first, over Task 2's fixture,
so Task 5 is a renderer. Nothing is on screen yet; the branch stays shippable.

**Files:**
- Create: `app/CicadaApp/Sources/CicadaApp/Models/ProjectBacklog.swift` — `BacklogStatus`, `BacklogLink`,
  `BacklogNote`, `BacklogItemSummary`, `BacklogItem`, `BacklogList`, `BacklogModel`
- Create: `app/CicadaApp/Sources/CicadaApp/Services/BacklogAPI.swift`
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Projects/BacklogCache.swift` — `BacklogCache`, `BacklogRefresh`
- Create: `app/CicadaApp/Sources/CicadaApp/Sync/BacklogMutations.swift` — `BacklogChange`, `BacklogWrite`,
  `BacklogWriteFailure`
- Modify: `app/CicadaApp/Sources/CicadaApp/Sync/SyncAPI.swift:112-119` — three requirements
- Modify: `app/CicadaApp/Sources/CicadaApp/Services/APIClient.swift` — their implementation, after the Projects
  extension (`:2585-2640`)
- Modify: `app/CicadaApp/Sources/CicadaApp/Theme/Copy+Projects.swift` — `Copy.Projects.Backlog`
- Modify: `app/CicadaApp/Tests/CicadaAppTests/StoreTests.swift` — `FakeSyncAPI` gains the three writes
- Test: `app/CicadaApp/Tests/CicadaAppTests/ProjectBacklogTests.swift` (new; also holds `BacklogFixtures` and
  `FakeBacklogAPI`)

**Interfaces:**
- Produces: the wire types above (every property `var`, so the cache can paint a status); `BacklogModel.tabs(_:)`,
  `rows(_:tab:)`, `defaultTab(_:)`, `openCount(_:)`, `emptyLine(tab:)`, `age(_:today:locale:)`, `triageLabel(_:)`,
  `statusLabel(_:)`, `moves(from:)`, `moveLabel(_:)`, `moveHelp(_:)`, `modelWords(_:)`, `authorLine(_:)`,
  `addedLine(_:today:locale:)`, `accessibilityLabel(_:today:locale:)`; `BacklogAPI`, `APIClient.backlogPath`;
  `BacklogCache` (`list(_:)`, `item(_:_:)`, `listPhase`, `itemPhase`, `refreshList`, `refreshItem`, `paint`,
  `unpaint`, `reset`, `key`); `BacklogRefresh`; `BacklogChange`, `BacklogWrite` (`result`, `paint`),
  `BacklogWriteFailure`; `SyncAPI.addBacklogItem` / `addBacklogNote` / `updateBacklogItem`.
- Consumes: `backlog-demo.json` (Task 2), `Conditional`, `getConditional`, `APIClient.projectPath`,
  `ProjectWriteFailure.detail`, `RelativeDay`, `ISODay`, `UsageFormat`, `ContributorIdentity.displayName`,
  `TextTab`, `MutationMemo`, `Copy.Projects.loadFailed` / `sleepBusy` / `backendDown`.

- [ ] **Step 1: Failing tests.** Create `app/CicadaApp/Tests/CicadaAppTests/ProjectBacklogTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// G150 R-B26 — the demo scenario's backlog wire, generated from a fresh `demo_bank.populate(today=2026-09-23)` by
/// `api/tests/test_backlog_app_fixture.py`, which also fails on any drift (R-PP27's precedent). Synthetic only.
enum BacklogFixtures {
    struct Wire: Decodable {
        let today: String
        let list: BacklogList
        let item: BacklogItem
    }

    static let today = ISODay(year: 2026, month: 9, day: 23)

    /// Resolved from THIS file's own path, never a caller's `#filePath` (`ProjectFixtures`' rule).
    private static let url = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent()   // CicadaAppTests
        .deletingLastPathComponent()   // Tests
        .appendingPathComponent("fixtures/backlog-demo.json")

    static func load(file: StaticString = #filePath, line: UInt = #line) throws -> Wire {
        let wire = try JSONDecoder().decode(Wire.self, from: Data(contentsOf: url))
        XCTAssertEqual(wire.list.items.count, 5, "read \(url.path) — a test over no items passes vacuously",
                       file: file, line: line)
        return wire
    }
}

/// A `BacklogAPI` that answers from a queue and records the ETag each call sent (`FakeProjectsAPI`'s twin).
@MainActor
final class FakeBacklogAPI: BacklogAPI {
    var listReplies: [String: [Result<Conditional<BacklogList>, any Error>]] = [:]
    var itemReplies: [String: [Result<Conditional<BacklogItem>, any Error>]] = [:]
    private(set) var listETags: [String: [String?]] = [:]
    private(set) var itemETags: [String: [String?]] = [:]

    func fetchBacklog(project: String, etag: String?) async throws -> Conditional<BacklogList> {
        listETags[project, default: []].append(etag)
        guard var queue = listReplies[project], !queue.isEmpty else { throw APIError.serverUnreachable }
        let next = queue.removeFirst()
        listReplies[project] = queue
        return try next.get()
    }

    func fetchBacklogItem(project: String, item: String, etag: String?) async throws -> Conditional<BacklogItem> {
        let key = BacklogCache.key(project, item)
        itemETags[key, default: []].append(etag)
        guard var queue = itemReplies[key], !queue.isEmpty else { throw APIError.serverUnreachable }
        let next = queue.removeFirst()
        itemReplies[key] = queue
        return try next.get()
    }
}

/// G150 — the backlog's wire, its pure decisions, its cache and its writes (R-B18, R-B19, R-B22).
@MainActor
final class ProjectBacklogTests: XCTestCase {
    private let us = Locale(identifier: "en_US")

    private func fresh<T>(_ v: T, _ etag: String) -> Result<Conditional<T>, any Error> {
        .success(Conditional(value: v, etag: etag, notModified: false))
    }

    private func notModified<T>(_ etag: String) -> Result<Conditional<T>, any Error> {
        .success(Conditional(value: nil, etag: etag, notModified: true))
    }

    // MARK: The wire

    func testTheDemoWireDecodes() throws {
        let wire = try BacklogFixtures.load()
        XCTAssertEqual(wire.list.prefix, "RAP")
        XCTAssertEqual(wire.list.items.map(\.id), ["RAP5", "RAP3", "RAP4", "RAP2", "RAP1"])
        XCTAssertEqual([BacklogStatus.open, .doing, .done, .dropped].map { wire.list.count($0) }, [2, 1, 1, 1])
        XCTAssertEqual(wire.item.id, "RAP3")
        XCTAssertEqual(wire.item.notes.map(\.byLabel), ["Claude Code", "You"])
        XCTAssertEqual(wire.item.notes.map(\.byKind), ["harness", "user"])
        XCTAssertNil(wire.item.notes[0].authorModel)
        XCTAssertFalse(wire.item.descriptionText.isEmpty)
    }

    func testAPayloadMissingOptionalFieldsStillDecodes() throws {
        let json = #"{"id": "AP1", "project": "alpha-project", "title": "X", "status": "open"}"#
        let item = try JSONDecoder().decode(BacklogItem.self, from: Data(json.utf8))
        XCTAssertEqual(item.summary.noteCount, 0)
        XCTAssertEqual(item.notes, [])
        XCTAssertEqual(item.summary.backlogStatus, .open)
        let odd = try JSONDecoder().decode(BacklogItemSummary.self, from: Data(#"{"id": "AP2", "status": "someday"}"#.utf8))
        XCTAssertEqual(odd.backlogStatus, .open, "an unknown state reads as open, never a crash")
    }

    // MARK: The model (R-B19)

    func testTabsCountEveryStateAndOnlyAllHoldsTheDropped() throws {
        let list = try BacklogFixtures.load().list
        let tabs = BacklogModel.tabs(list)
        XCTAssertEqual(tabs.map(\.label), ["Open", "Doing", "Done", "All"])
        XCTAssertEqual(tabs.map(\.count), [2, 1, 1, 5])
        XCTAssertEqual(BacklogModel.rows(list, tab: .open).map(\.id), ["RAP3", "RAP4"], "the server's order is kept")
        XCTAssertEqual(BacklogModel.rows(list, tab: nil).count, 5)
        XCTAssertFalse(BacklogModel.rows(list, tab: .done).contains { $0.backlogStatus == .dropped })
        XCTAssertEqual(BacklogModel.defaultTab(list), .open)
        XCTAssertEqual(BacklogModel.openCount(list), 3)
    }

    func testTheDefaultTabIsTheFirstThatHoldsAnything() throws {
        var list = try BacklogFixtures.load().list
        list.counts = ["open": 0, "doing": 0, "done": 3, "dropped": 1]
        XCTAssertEqual(BacklogModel.defaultTab(list), .done)
        list.counts = [:]
        XCTAssertEqual(BacklogModel.defaultTab(list), .open)
    }

    func testTheAgeIsTheLastNoteElseTheItemWithTheFullDateAsHelp() throws {
        let rows = Dictionary(uniqueKeysWithValues: try BacklogFixtures.load().list.items.map { ($0.id, $0) })
        let today = BacklogFixtures.today
        let rap3 = try XCTUnwrap(rows["RAP3"])
        XCTAssertEqual(BacklogModel.age(rap3, today: today, locale: us).text, "3d")
        XCTAssertEqual(BacklogModel.age(rap3, today: today, locale: us).help, "Sunday, September 20, 2026")
        XCTAssertEqual(BacklogModel.age(try XCTUnwrap(rows["RAP4"]), today: today, locale: us).text, "6d",
                       "no note: the item's own day")
    }

    func testMovesFollowTheStateAndSayWhatTheyDo() {
        XCTAssertEqual(BacklogModel.moves(from: .open), [.doing, .done, .dropped])
        XCTAssertEqual(BacklogModel.moves(from: .doing), [.done, .dropped])
        XCTAssertEqual(BacklogModel.moves(from: .done), [.open])
        XCTAssertEqual(BacklogModel.moves(from: .dropped), [.open])
        XCTAssertEqual(BacklogStatus.allCases.map(BacklogModel.moveLabel), ["Reopen", "Start", "Mark done", "Drop"])
        XCTAssertEqual(BacklogModel.triageLabel("research"), "Research")
        XCTAssertNil(BacklogModel.triageLabel(nil))
        XCTAssertEqual(BacklogModel.emptyLine(tab: .doing), "Nothing in progress.")
    }

    func testAnAuthorIsNamedInWordsWithTheTurnsModelWhenTheWireKnowsIt() throws {
        let note = try XCTUnwrap(BacklogFixtures.load().item.notes.first)
        XCTAssertEqual(BacklogModel.authorLine(note), "Claude Code")
        var known = note
        known.authorModel = "claude-opus-5-5"
        known.authorEffort = "high"
        XCTAssertEqual(BacklogModel.authorLine(known), "Claude Code · Opus 5.5 · high effort")
        known.authorEffort = "xhigh"
        XCTAssertEqual(BacklogModel.authorLine(known), "Claude Code · Opus 5.5 · extra-high effort")
        XCTAssertEqual(BacklogModel.modelWords("claude-sonnet-5"), "Sonnet 5")
        XCTAssertEqual(BacklogModel.modelWords("gpt-5.5-codex"), "gpt-5.5-codex", "an unknown family reads as its id")
    }

    func testTheItemsHeadingLineSaysWhoAddedItAndWhen() throws {
        let item = try BacklogFixtures.load().item
        XCTAssertEqual(BacklogModel.addedLine(item.summary, today: BacklogFixtures.today, locale: us),
                       "Added by Claude Code · Sep 11")
    }

    // MARK: The cache (R-B18)

    func testTheListIsRevalidatedWithItsETagAndAMoveIsPaintedUntilUnpainted() async throws {
        let api = FakeBacklogAPI()
        api.listReplies["rover-arm-project"] = [fresh(try BacklogFixtures.load().list, "l1"), notModified("l1")]
        let cache = BacklogCache(api: api)
        await cache.refreshList("rover-arm-project")
        await cache.refreshList("rover-arm-project")
        XCTAssertEqual(api.listETags["rover-arm-project"], [nil, "l1"])
        XCTAssertEqual(cache.list("rover-arm-project")?.items.count, 5, "a 304 keeps what was read")
        cache.paint("rover-arm-project", "RAP3", .done)
        let painted = try XCTUnwrap(cache.list("rover-arm-project"))
        XCTAssertEqual(painted.items.first { $0.id == "RAP3" }?.status, "done")
        XCTAssertEqual([painted.count(.open), painted.count(.done)], [1, 2])
        cache.unpaint("rover-arm-project", "RAP3")
        XCTAssertEqual(cache.list("rover-arm-project")?.count(.open), 2)
    }

    func testAMissingProjectIsGoneAndABankSwitchForgetsEverything() async throws {
        let api = FakeBacklogAPI()
        api.listReplies["nope"] = [.failure(APIError.httpError(404, "{}"))]
        api.itemReplies["rover-arm-project/RAP3"] = [fresh(try BacklogFixtures.load().item, "i1")]
        let cache = BacklogCache(api: api)
        await cache.refreshList("nope")
        XCTAssertEqual(cache.listPhase("nope"), .gone)
        await cache.refreshItem("rover-arm-project", "RAP3")
        XCTAssertEqual(cache.item("rover-arm-project", "RAP3")?.summary.title,
                       "Swap the gripper camera for a global-shutter one")
        cache.reset()
        XCTAssertNil(cache.item("rover-arm-project", "RAP3"))
        XCTAssertEqual(cache.listPhase("nope"), .idle)
    }

    func testTheSectionAsksAgainOnlyWhenWhatItsETagsFoldMoves() {
        let a = VersionVector(version: "1", components: ["backlog": "0:0:0", "entities": "1", "episodes": "1",
                                                        "bank": "b"])
        var moved = a.components
        moved["backlog"] = "1:1:9"
        XCTAssertTrue(BacklogRefresh.shouldRevalidate(old: a, new: VersionVector(version: "2", components: moved)))
        var unrelated = a.components
        unrelated["episodes"] = "2"
        XCTAssertFalse(BacklogRefresh.shouldRevalidate(old: a, new: VersionVector(version: "3", components: unrelated)))
    }

    // MARK: Writes (R-B22)

    private func harness() async throws -> (Store, FakeSyncAPI, BacklogCache) {
        let api = FakeSyncAPI()
        let store = Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: api)
        let reads = FakeBacklogAPI()
        reads.listReplies["rover-arm-project"] = [fresh(try BacklogFixtures.load().list, "l1")]
        let cache = BacklogCache(api: reads)
        await cache.refreshList("rover-arm-project")
        return (store, api, cache)
    }

    func testAMoveIsPaintedAtOnceAndSent() async throws {
        let (store, api, cache) = try await harness()
        api.backlogReply = try BacklogFixtures.load().item
        let write = BacklogWrite(projectId: "rover-arm-project",
                                 action: .update(item: "RAP4", change: BacklogChange(status: "done")), cache: cache)
        api.gateWrites = true
        let running = Task { await store.perform(write) }
        await api.waitForParkedWrite()
        XCTAssertEqual(cache.list("rover-arm-project")?.items.first { $0.id == "RAP4" }?.status, "done",
                       "painted before the server answers")
        api.releaseWriteGate()
        let ok = await running.value
        XCTAssertTrue(ok)
        XCTAssertEqual(api.writes.last, "updateBacklogItem:rover-arm-project:RAP4:done:nil")
        XCTAssertEqual(write.result?.id, "RAP3")
    }

    func testA409RollsTheMoveBackAndSaysTheServersSentence() async throws {
        let (store, api, cache) = try await harness()
        api.backlogError = APIError.httpError(409, #"{"detail": "Sleep is writing memory right now, try again in a moment"}"#)
        let write = BacklogWrite(projectId: "rover-arm-project",
                                 action: .note(item: "RAP4", text: "Done.", status: .done), cache: cache)
        let ok = await store.perform(write)
        XCTAssertFalse(ok)
        XCTAssertEqual(cache.list("rover-arm-project")?.items.first { $0.id == "RAP4" }?.status, "open")
        XCTAssertEqual(store.toast, "Sleep is writing memory right now, try again in a moment")
        XCTAssertEqual(api.writes.last, "addBacklogNote:rover-arm-project:RAP4:done")
    }

    func testAnAddPaintsNothingAndA400SaysThePagesOwnWords() async throws {
        let (store, api, cache) = try await harness()
        api.backlogError = APIError.httpError(400, #"{"detail": "links is a list of {kind, ref}; nothing was written"}"#)
        let write = BacklogWrite(projectId: "rover-arm-project", action: .add(title: "New", description: ""),
                                 cache: cache)
        XCTAssertNil(write.paint)
        _ = await store.perform(write)
        XCTAssertEqual(store.toast, Copy.Projects.Backlog.saveFailed)
        XCTAssertEqual(api.writes.last, "addBacklogItem:rover-arm-project:New")
    }
}
```

(The RAP3 item was added at T−12 = 2026-09-11 by `claude-code`, so its heading line reads "Added by Claude Code · Sep
11"; 2026-09-20 is a Sunday.)

In `Tests/CicadaAppTests/StoreTests.swift`, inside `FakeSyncAPI`, after the Projects writes (`:183-213`):

```swift
    // MARK: Backlog (G150)

    /// What every backlog write answers; set `backlogError` to drive a rollback.
    var backlogReply: BacklogItem?
    var backlogError: (any Error)?

    private func backlogWrite(_ what: String) async throws -> BacklogItem {
        try await record(what)
        if let backlogError { throw backlogError }
        guard let backlogReply else { throw APIError.serverUnreachable }
        return backlogReply
    }

    func addBacklogItem(project: String, title: String, description: String) async throws -> BacklogItem {
        try await backlogWrite("addBacklogItem:\(project):\(title)")
    }
    func addBacklogNote(project: String, item: String, note: String, status: String?) async throws -> BacklogItem {
        try await backlogWrite("addBacklogNote:\(project):\(item):\(status ?? "nil")")
    }
    func updateBacklogItem(project: String, item: String, change: BacklogChange) async throws -> BacklogItem {
        try await backlogWrite("updateBacklogItem:\(project):\(item):\(change.status ?? "nil"):\(change.title ?? "nil")")
    }
```

Run: `cd <worktree>/app/CicadaApp && swift build --build-tests 2>&1 | tail -5` → the types do not exist. That is the
red.

- [ ] **Step 2: The wire and the model.** Create `app/CicadaApp/Sources/CicadaApp/Models/ProjectBacklog.swift`:

```swift
import Foundation

/// G150 — a project's backlog on the wire (`api/routers/backlog.py`). Decoded leniently like every Projects type
/// (R-PP2's reason): a server that adds or drops a field never blanks the section. Not a Store domain —
/// `BacklogCache` fetches it on demand (R-B18). Every property is `var` so the cache can paint a status move before
/// the server answers (R-B22).
enum BacklogStatus: String, CaseIterable, Hashable, Sendable {
    case open, doing, done, dropped
}

struct BacklogLink: Decodable, Equatable, Hashable, Sendable {
    var kind: String
    var ref: String
}

/// One signed note (R-B4). `by` is the author id (`user`, a harness label, `cicada`), `byLabel` the heading's words.
/// `authorModel`/`authorEffort` are the turn's model and effort for a harness note once round 4's join fills them
/// (R-B6); nil until then — never guessed here.
struct BacklogNote: Equatable, Sendable {
    var day: String
    var text: String
    var by: String
    var byKind: String
    var byProvider: String?
    var byLabel: String
    var at: String?
    var session: String?
    var authorModel: String?
    var authorEffort: String?
}

extension BacklogNote: Decodable {
    enum CodingKeys: String, CodingKey {
        case day, text, by, byKind, byProvider, byLabel, at, session, authorModel, authorEffort
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        day = try c.decodeIfPresent(String.self, forKey: .day) ?? ""
        text = try c.decodeIfPresent(String.self, forKey: .text) ?? ""
        by = try c.decodeIfPresent(String.self, forKey: .by) ?? "agent"
        byKind = try c.decodeIfPresent(String.self, forKey: .byKind) ?? "harness"
        byProvider = try c.decodeIfPresent(String.self, forKey: .byProvider)
        byLabel = try c.decodeIfPresent(String.self, forKey: .byLabel) ?? ""
        at = try c.decodeIfPresent(String.self, forKey: .at)
        session = try c.decodeIfPresent(String.self, forKey: .session)
        authorModel = try c.decodeIfPresent(String.self, forKey: .authorModel)
        authorEffort = try c.decodeIfPresent(String.self, forKey: .authorEffort)
    }
}

struct BacklogItemSummary: Equatable, Identifiable, Sendable {
    var id: String
    var project: String
    var title: String
    var status: String
    var triage: String?
    var paid: Bool
    var created: String
    var updated: String
    var addedBy: String
    var addedByKind: String
    var addedByLabel: String
    var noteCount: Int
    var lastNoteDay: String?
    var lastNoteBy: String?
    var order: Int?

    /// An unknown state reads as open — the item is still on the list, never dropped from view by a newer server.
    var backlogStatus: BacklogStatus { BacklogStatus(rawValue: status) ?? .open }
}

extension BacklogItemSummary: Decodable {
    enum CodingKeys: String, CodingKey {
        case id, project, title, status, triage, paid, created, updated, addedBy, addedByKind, addedByLabel
        case noteCount, lastNoteDay, lastNoteBy, order
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        project = try c.decodeIfPresent(String.self, forKey: .project) ?? ""
        title = try c.decodeIfPresent(String.self, forKey: .title) ?? id
        status = try c.decodeIfPresent(String.self, forKey: .status) ?? "open"
        triage = try c.decodeIfPresent(String.self, forKey: .triage)
        paid = try c.decodeIfPresent(Bool.self, forKey: .paid) ?? false
        created = try c.decodeIfPresent(String.self, forKey: .created) ?? ""
        updated = try c.decodeIfPresent(String.self, forKey: .updated) ?? created
        addedBy = try c.decodeIfPresent(String.self, forKey: .addedBy) ?? "user"
        addedByKind = try c.decodeIfPresent(String.self, forKey: .addedByKind) ?? "user"
        addedByLabel = try c.decodeIfPresent(String.self, forKey: .addedByLabel) ?? ""
        noteCount = try c.decodeIfPresent(Int.self, forKey: .noteCount) ?? 0
        lastNoteDay = try c.decodeIfPresent(String.self, forKey: .lastNoteDay)
        lastNoteBy = try c.decodeIfPresent(String.self, forKey: .lastNoteBy)
        order = try c.decodeIfPresent(Int.self, forKey: .order)
    }
}

/// An item in full: the summary's fields plus its reasoning, its notes, its links and its file (in `.help` only).
struct BacklogItem: Equatable, Identifiable, Sendable {
    var summary: BacklogItemSummary
    var descriptionText: String
    var notes: [BacklogNote]
    var links: [BacklogLink]
    var session: String?
    var path: String

    var id: String { summary.id }
}

extension BacklogItem: Decodable {
    enum CodingKeys: String, CodingKey {
        case descriptionText = "description"
        case notes, links, session, path
    }

    init(from decoder: Decoder) throws {
        summary = try BacklogItemSummary(from: decoder)
        let c = try decoder.container(keyedBy: CodingKeys.self)
        descriptionText = try c.decodeIfPresent(String.self, forKey: .descriptionText) ?? ""
        notes = try c.decodeIfPresent([BacklogNote].self, forKey: .notes) ?? []
        links = try c.decodeIfPresent([BacklogLink].self, forKey: .links) ?? []
        session = try c.decodeIfPresent(String.self, forKey: .session)
        path = try c.decodeIfPresent(String.self, forKey: .path) ?? ""
    }
}

struct BacklogList: Equatable, Sendable {
    var project: String
    var projectName: String
    var prefix: String
    var counts: [String: Int]
    var items: [BacklogItemSummary]
    var tzName: String

    func count(_ status: BacklogStatus) -> Int { counts[status.rawValue] ?? 0 }
}

extension BacklogList: Decodable {
    enum CodingKeys: String, CodingKey { case project, projectName, prefix, counts, items, tzName }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        project = try c.decodeIfPresent(String.self, forKey: .project) ?? ""
        projectName = try c.decodeIfPresent(String.self, forKey: .projectName) ?? project
        prefix = try c.decodeIfPresent(String.self, forKey: .prefix) ?? ""
        counts = (try? c.decodeIfPresent([String: Int].self, forKey: .counts)) ?? [:]
        items = try c.decodeIfPresent([BacklogItemSummary].self, forKey: .items) ?? []
        tzName = try c.decodeIfPresent(String.self, forKey: .tzName) ?? "UTC"
    }
}

/// G150 — every decision the Backlog section and the item card make, pure (the `ProjectsModel` pattern): `today` is
/// an argument, so a test pins it and midnight re-derives every word with no network (DR-58).
enum BacklogModel {
    /// R-B19 (DR-45) — Open · Doing · Done, and All as the tabs' nil: a dropped item shows only under All.
    static func tabs(_ list: BacklogList) -> [TextTab<BacklogStatus>] {
        [TextTab(id: .open, label: Copy.Projects.Backlog.open, count: list.count(.open)),
         TextTab(id: .doing, label: Copy.Projects.Backlog.doing, count: list.count(.doing)),
         TextTab(id: .done, label: Copy.Projects.Backlog.done, count: list.count(.done)),
         TextTab(id: nil, label: Copy.Projects.Backlog.all, count: list.counts.values.reduce(0, +))]
    }

    /// The server's order (R-B19), filtered by the tab; nil is All.
    static func rows(_ list: BacklogList, tab: BacklogStatus?) -> [BacklogItemSummary] {
        list.items.filter { tab == nil || $0.backlogStatus == tab }
    }

    /// The first of Open, Doing, Done that holds anything — a backlog that is all done opens on Done, never on an
    /// empty Open.
    static func defaultTab(_ list: BacklogList) -> BacklogStatus? {
        [BacklogStatus.open, .doing, .done].first { list.count($0) > 0 } ?? .open
    }

    /// What a folded section says beside its label (R-B19): items open or doing.
    static func openCount(_ list: BacklogList) -> Int { list.count(.open) + list.count(.doing) }

    static func emptyLine(tab: BacklogStatus?) -> String {
        switch tab {
        case .open?: Copy.Projects.Backlog.emptyOpen
        case .doing?: Copy.Projects.Backlog.emptyDoing
        case .done?: Copy.Projects.Backlog.emptyDone
        case .dropped?: Copy.Projects.Backlog.emptyDropped
        case nil: Copy.Projects.Backlog.emptyAll
        }
    }

    /// DR-58 — the age of the last note, else of the item, computed at read from an absolute day; the full date is
    /// the `.help`.
    static func age(_ row: BacklogItemSummary, today: ISODay,
                    locale: Locale = .autoupdatingCurrent) -> (text: String, help: String) {
        guard let day = ISODay(row.lastNoteDay ?? row.created) else { return ("", "") }
        return (RelativeDay.compactAge(day, today: today), RelativeDay.full(day, locale: locale))
    }

    static func triageLabel(_ triage: String?) -> String? {
        switch triage {
        case "apply": Copy.Projects.Backlog.apply
        case "research": Copy.Projects.Backlog.research
        case "decide": Copy.Projects.Backlog.decide
        default: nil
        }
    }

    static func statusLabel(_ status: BacklogStatus) -> String {
        switch status {
        case .open: Copy.Projects.Backlog.open
        case .doing: Copy.Projects.Backlog.doing
        case .done: Copy.Projects.Backlog.done
        case .dropped: Copy.Projects.Backlog.dropped
        }
    }

    /// R-B20 — the moves an item can make from where it stands.
    static func moves(from status: BacklogStatus) -> [BacklogStatus] {
        switch status {
        case .open: [.doing, .done, .dropped]
        case .doing: [.done, .dropped]
        case .done, .dropped: [.open]
        }
    }

    static func moveLabel(_ to: BacklogStatus) -> String {
        switch to {
        case .open: Copy.Projects.Backlog.reopen
        case .doing: Copy.Projects.Backlog.start
        case .done: Copy.Projects.Backlog.markDone
        case .dropped: Copy.Projects.Backlog.drop
        }
    }

    static func moveHelp(_ to: BacklogStatus) -> String {
        switch to {
        case .open: Copy.Projects.Backlog.reopenHelp
        case .doing: Copy.Projects.Backlog.startHelp
        case .done: Copy.Projects.Backlog.markDoneHelp
        case .dropped: Copy.Projects.Backlog.dropHelp
        }
    }

    /// "claude-opus-5-5" → "Opus 5.5"; any other family reads as its own id (never a guess at a product name).
    static func modelWords(_ id: String) -> String {
        let parts = id.lowercased().split(separator: "-").map(String.init)
        guard parts.first == "claude", parts.count >= 2 else { return id }
        let family = parts[1].prefix(1).uppercased() + parts[1].dropFirst()
        let version = parts.dropFirst(2).filter { $0.allSatisfy(\.isNumber) }.joined(separator: ".")
        return version.isEmpty ? family : "\(family) \(version)"
    }

    /// R-B6 — who wrote a note, in words: "You", "Claude Code", and — when the wire carries the turn's model and
    /// effort — "Claude Code · Opus 5.5 · high effort".
    static func authorLine(_ note: BacklogNote) -> String {
        var bits = [note.byLabel.isEmpty ? ContributorIdentity.displayName(author: note.by, kind: note.byKind)
                                         : note.byLabel]
        if let model = note.authorModel, !model.isEmpty { bits.append(modelWords(model)) }
        if let effort = note.authorEffort, !effort.isEmpty { bits.append(Copy.Projects.Backlog.effort(effort)) }
        return bits.joined(separator: " · ")
    }

    /// The item card's blurb: who added it and on which day (DR-58's absolute form; the full date is `.help`).
    static func addedLine(_ row: BacklogItemSummary, today: ISODay, locale: Locale = .autoupdatingCurrent) -> String {
        let who = row.addedByLabel.isEmpty ? ContributorIdentity.displayName(author: row.addedBy, kind: row.addedByKind)
                                           : row.addedByLabel
        guard let day = ISODay(row.created) else { return Copy.Projects.Backlog.addedBy(who) }
        return Copy.Projects.Backlog.addedBy(who, day: RelativeDay.absolute(day, today: today, locale: locale))
    }

    /// VoiceOver hears the row the way the eye reads it: the id, the task, its state, its triage and its age.
    static func accessibilityLabel(_ row: BacklogItemSummary, today: ISODay,
                                   locale: Locale = .autoupdatingCurrent) -> String {
        [row.id, row.title, statusLabel(row.backlogStatus), triageLabel(row.triage),
         age(row, today: today, locale: locale).help].compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: ", ")
    }
}
```

- [ ] **Step 3: The words.** Append to `app/CicadaApp/Sources/CicadaApp/Theme/Copy+Projects.swift`:

```swift
extension Copy.Projects {
    /// G150 — the Backlog section and its item card. For a person (DR-59): no ids but an item's own address (R-B24),
    /// no prices ("Paid AI" says what a task needs, never what it costs), no day words — `RelativeDay` spells those
    /// (DR-58) — and never "Timeline" (R-PP12).
    enum Backlog {
        static let title = "Backlog"
        static let tabMenu = "Backlog"
        static let open = "Open"
        static let doing = "Doing"
        static let done = "Done"
        static let dropped = "Dropped"
        static let all = "All"
        static let apply = "Apply"
        static let research = "Research"
        static let decide = "Decide"
        static let paid = "Paid AI"
        static let add = "Add to backlog"
        static let addHelp = "Keep a task or an idea for later, with why it matters"
        static let titleLabel = "Task"
        static let titlePlaceholder = "The task, in a line"
        static let descriptionLabel = "Why"
        static let descriptionPlaceholder = "Why it matters — the problem, what you saw, what a fix must respect (optional)"
        static let reading = "Reading the backlog…"
        static let readingItem = "Reading the item…"
        static let failedTitle = "The backlog didn't load"
        static let itemFailedTitle = "This item didn't load"
        static let gone = "This item isn't on the project's backlog any more."
        static let saveFailed = "That change wasn't saved. Try again in a moment."
        static let description = "Description"
        static let noDescription = "No description yet."
        static let notes = "Notes"
        static let noNotes = "No notes yet."
        static let links = "Links"
        static let addNote = "Add a note"
        static let notePlaceholder = "What you found, decided or measured"
        static let saveNote = "Add note"
        static let saveNoteHelp = "Add this note, signed as you"
        static let editTitle = "Edit title"
        static let editTitleHelp = "Change how the task is worded"
        static let saveTitle = "Save"
        static let closeHelp = "Close the item"
        static let start = "Start"
        static let markDone = "Mark done"
        static let drop = "Drop"
        static let reopen = "Reopen"
        static let startHelp = "Mark it as being worked on"
        static let markDoneHelp = "Mark it done"
        static let dropHelp = "Set it aside for good — it stays under All"
        static let reopenHelp = "Put it back on the open list"
        static let emptyOpen = "Nothing open."
        static let emptyDoing = "Nothing in progress."
        static let emptyDone = "Nothing done yet."
        static let emptyDropped = "Nothing set aside."
        static let emptyAll = "Nothing on this backlog yet. Add a task, or ask an agent to put one here."

        static func openCount(_ n: Int) -> String { "\(UsageFormat.count(n)) open" }
        static func notesTitle(_ n: Int) -> String { n == 0 ? notes : "\(notes) · \(UsageFormat.count(n))" }
        static func addedBy(_ who: String) -> String { "Added by \(who)" }
        static func addedBy(_ who: String, day: String) -> String { "Added by \(who) · \(day)" }
        static func rowHelp(_ id: String) -> String { "Open \(id)" }
        static func itemHelp(_ id: String, path: String) -> String { path.isEmpty ? id : "\(id) · \(path)" }
        static func pullRequest(_ ref: String) -> String { "Pull request \(ref)" }

        /// A turn's reasoning effort in words (round 4's C1 enum: minimal, low, medium, high, xhigh, max).
        static func effort(_ raw: String) -> String {
            switch raw.lowercased() {
            case "xhigh": "extra-high effort"
            case "max": "maximum effort"
            default: "\(raw.lowercased()) effort"
            }
        }
    }
}
```

- [ ] **Step 4: The reads, the cache, the writes.** Create `app/CicadaApp/Sources/CicadaApp/Services/BacklogAPI.swift`:

```swift
import Foundation

/// G150 (R-B18) — the Backlog section's two reads. Not a Store domain: fetched on demand into `BacklogCache`,
/// revalidated with the ETag the server sends, no `VersionVector` mapping — the Projects reads' precedent
/// (`ProjectsAPI`). On a protocol so the cache's tests fake it.
protocol BacklogAPI: Sendable {
    func fetchBacklog(project: String, etag: String?) async throws -> Conditional<BacklogList>
    func fetchBacklogItem(project: String, item: String, etag: String?) async throws -> Conditional<BacklogItem>
}

extension APIClient: BacklogAPI {
    /// `/backlog/<project>/<item>/<tail…>`, every component encoded the way `projectPath` encodes one — an id never
    /// reshapes the URL.
    nonisolated static func backlogPath(_ project: String, _ item: String, _ tail: String...) -> String {
        var allowed = CharacterSet.urlPathAllowed
        allowed.remove(charactersIn: "/?#")
        return "/backlog/" + ([project, item] + tail)
            .map { $0.addingPercentEncoding(withAllowedCharacters: allowed) ?? $0 }
            .joined(separator: "/")
    }

    func fetchBacklog(project: String, etag: String?) async throws -> Conditional<BacklogList> {
        try await getConditional(Self.projectPath(project, "backlog"), etag: etag)
    }

    func fetchBacklogItem(project: String, item: String, etag: String?) async throws -> Conditional<BacklogItem> {
        try await getConditional(Self.backlogPath(project, item), etag: etag)
    }
}
```

Create `app/CicadaApp/Sources/CicadaApp/Views/Projects/BacklogCache.swift`:

```swift
import Foundation
import Observation

/// G150 (R-B18) — the Backlog section's in-memory cache, `ProjectsCache`'s twin: one for the app, owned by
/// `CicadaApp`, revalidated with the server's ETag when the section appears, an item opens, a write lands, or a sync
/// event moves `backlog`/`entities`/`bank` (`BacklogRefresh`); emptied on a bank switch (ids repeat across banks), and
/// an answer in flight across the switch is dropped by its epoch. Never blank: a failed or 304 answer keeps the last
/// value (DR-43). Only a status move is painted before the server answers (R-B22).
@Observable
@MainActor
final class BacklogCache {
    enum Phase: Equatable { case idle, loading, loaded, gone, failed(String) }

    /// An item is a few KB; twenty covers an afternoon of reading.
    static let itemCapacity = 20

    private(set) var lists: [String: BacklogList] = [:]
    private(set) var listPhases: [String: Phase] = [:]
    private(set) var items: [String: BacklogItem] = [:]
    private(set) var itemPhases: [String: Phase] = [:]
    /// R-B22 — status moves painted over the server's answer, keyed `project/item`, until an answer holds them.
    private(set) var paints: [String: BacklogStatus] = [:]

    @ObservationIgnored private let api: any BacklogAPI
    @ObservationIgnored private var listETags: [String: String] = [:]
    @ObservationIgnored private var itemETags: [String: String] = [:]
    @ObservationIgnored private var recent: [String] = []
    @ObservationIgnored private var epoch = 0

    init(api: any BacklogAPI = APIClient.shared) { self.api = api }

    nonisolated static func key(_ project: String, _ item: String) -> String { "\(project)/\(item)" }

    func listPhase(_ project: String) -> Phase { listPhases[project] ?? .idle }
    func itemPhase(_ project: String, _ item: String) -> Phase { itemPhases[Self.key(project, item)] ?? .idle }

    /// What the section draws: the server's list with every pending move painted over it, counts included.
    func list(_ project: String) -> BacklogList? {
        guard var list = lists[project] else { return nil }
        for i in list.items.indices {
            let old = list.items[i].status
            guard let painted = paints[Self.key(project, list.items[i].id)], painted.rawValue != old else { continue }
            list.counts[old] = max(0, (list.counts[old] ?? 0) - 1)
            list.counts[painted.rawValue, default: 0] += 1
            list.items[i].status = painted.rawValue
        }
        return list
    }

    func item(_ project: String, _ item: String) -> BacklogItem? {
        guard var value = items[Self.key(project, item)] else { return nil }
        if let painted = paints[Self.key(project, item)] { value.summary.status = painted.rawValue }
        return value
    }

    func paint(_ project: String, _ item: String, _ status: BacklogStatus) { paints[Self.key(project, item)] = status }

    func unpaint(_ project: String, _ item: String) { paints[Self.key(project, item)] = nil }

    /// Forget everything — a bank switch (`ContentView`, R-PU26's reason).
    func reset() {
        epoch &+= 1
        lists = [:]
        listPhases = [:]
        items = [:]
        itemPhases = [:]
        paints = [:]
        listETags = [:]
        itemETags = [:]
        recent = []
    }

    func refreshList(_ project: String) async {
        let started = epoch
        if lists[project] == nil { listPhases[project] = .loading }
        do {
            // Never an ETag with nothing cached: a 304 would leave the section with nothing to draw.
            let answer = try await api.fetchBacklog(project: project, etag: lists[project] == nil ? nil : listETags[project])
            guard started == epoch else { return }
            if let value = answer.value {
                lists[project] = value
                listETags[project] = answer.etag
                // A fresh answer that holds a painted move settles it.
                for row in value.items where paints[Self.key(project, row.id)]?.rawValue == row.status {
                    paints[Self.key(project, row.id)] = nil
                }
            }
            listPhases[project] = .loaded
        } catch APIError.httpError(404, _) {
            guard started == epoch else { return }
            lists[project] = nil
            listETags[project] = nil
            listPhases[project] = .gone
        } catch {
            guard started == epoch else { return }
            listPhases[project] = lists[project] == nil ? .failed(Copy.Projects.loadFailed(error)) : .loaded
        }
    }

    func refreshItem(_ project: String, _ item: String) async {
        let key = Self.key(project, item)
        let started = epoch
        if items[key] == nil { itemPhases[key] = .loading }
        do {
            let answer = try await api.fetchBacklogItem(project: project, item: item,
                                                        etag: items[key] == nil ? nil : itemETags[key])
            guard started == epoch else { return }
            if let value = answer.value {
                store(value, etag: answer.etag, key: key)
                if paints[key]?.rawValue == value.summary.status { paints[key] = nil }
            }
            itemPhases[key] = .loaded
        } catch APIError.httpError(404, _) {
            guard started == epoch else { return }
            items[key] = nil
            itemETags[key] = nil
            itemPhases[key] = .gone
        } catch {
            guard started == epoch else { return }
            itemPhases[key] = items[key] == nil ? .failed(Copy.Projects.loadFailed(error)) : .loaded
        }
    }

    private func store(_ value: BacklogItem, etag: String?, key: String) {
        items[key] = value
        itemETags[key] = etag
        recent.removeAll { $0 == key }
        recent.append(key)
        while recent.count > Self.itemCapacity {
            let old = recent.removeFirst()
            items[old] = nil
            itemETags[old] = nil
            itemPhases[old] = nil
        }
    }
}

/// R-B18 — when the Projects page asks the backlog again: a sync version event that moved what its ETags fold
/// (`backlog`, `entities`) or the bank itself. A Sleep tick alone does not: nothing the section shows moved.
enum BacklogRefresh {
    static let components = ["backlog", "entities", "bank"]

    static func shouldRevalidate(old: VersionVector?, new: VersionVector?) -> Bool {
        guard let new else { return false }
        guard let old else { return true }
        return components.contains { old.components[$0] != new.components[$0] }
    }
}
```

Create `app/CicadaApp/Sources/CicadaApp/Sync/BacklogMutations.swift`:

```swift
import Foundation

/// `PATCH /backlog/{project}/{item}` from the app — a title or a status (R-B20: triage, `paid` and links stay for
/// agents and scripts in v1).
struct BacklogChange: Equatable, Sendable {
    var title: String?
    var status: String?

    var body: [String: Any] {
        var body: [String: Any] = [:]
        if let title { body["title"] = title }
        if let status { body["status"] = status }
        return body
    }
}

/// G150 (R-B22) — one of the Backlog section's three writes, run by `Store.perform` like every write the app sends.
/// Only a status move is painted before the server answers (its result is known); a failure rolls it back and
/// toasts in plain words; the server's answer — the item as it now stands — is kept in `result`, so an add can open
/// what it filed. `refreshDomains` is empty: the page revalidates `BacklogCache` itself.
struct BacklogWrite: Mutation {
    enum Action: Equatable {
        case add(title: String, description: String)
        case note(item: String, text: String, status: BacklogStatus?)
        case update(item: String, change: BacklogChange)
    }

    let projectId: String
    let action: Action
    let cache: BacklogCache
    private let memo = MutationMemo<BacklogItem>()
    private let failure = MutationMemo<any Error>()

    init(projectId: String, action: Action, cache: BacklogCache) {
        self.projectId = projectId
        self.action = action
        self.cache = cache
    }

    var result: BacklogItem? { memo.value }

    /// The move this write paints, if any.
    var paint: (item: String, status: BacklogStatus)? {
        switch action {
        case .add:
            return nil
        case .note(let item, _, let status):
            return status.map { (item: item, status: $0) }
        case .update(let item, let change):
            return change.status.flatMap(BacklogStatus.init(rawValue:)).map { (item: item, status: $0) }
        }
    }

    func optimistic(_ store: Store) async {
        if let paint { cache.paint(projectId, paint.item, paint.status) }
    }

    func request(_ api: any SyncAPI) async throws {
        do {
            switch action {
            case .add(let title, let description):
                memo.value = try await api.addBacklogItem(project: projectId, title: title, description: description)
            case .note(let item, let text, let status):
                memo.value = try await api.addBacklogNote(project: projectId, item: item, note: text,
                                                          status: status?.rawValue)
            case .update(let item, let change):
                memo.value = try await api.updateBacklogItem(project: projectId, item: item, change: change)
            }
        } catch {
            failure.value = error
            throw error
        }
    }

    func rollback(_ store: Store) async {
        if let paint { cache.unpaint(projectId, paint.item) }
    }

    var failureMessage: String { BacklogWriteFailure.message(failure.value) }
}

/// R-B22 — a failed write in words: a 409 carries `routers/backlog.py`'s own sentence (Sleep is writing, or the idea
/// is already on the backlog — both written for the person); every other failure gets this section's words, because
/// a 400's or a 404's detail names fields and ids (DR-54).
enum BacklogWriteFailure {
    static func message(_ error: (any Error)?) -> String {
        guard let api = error as? APIError else { return Copy.Projects.Backlog.saveFailed }
        switch api {
        case .httpError(409, let body):
            return ProjectWriteFailure.detail(body) ?? Copy.Projects.sleepBusy
        case .httpError(404, _):
            return Copy.Projects.Backlog.gone
        case .serverUnreachable:
            return Copy.Projects.backendDown
        default:
            return Copy.Projects.Backlog.saveFailed
        }
    }
}
```

In `Sync/SyncAPI.swift`, after `withdrawProjectHappening` (`:119`):

```swift
    /// G150 — the Backlog section's three writes (`routers/backlog.py`), each answering the item as it now stands. All
    /// answer 409 while a Sleep cycle runs, and an add whose idea is already open answers 409 naming the item.
    func addBacklogItem(project: String, title: String, description: String) async throws -> BacklogItem
    func addBacklogNote(project: String, item: String, note: String, status: String?) async throws -> BacklogItem
    func updateBacklogItem(project: String, item: String, change: BacklogChange) async throws -> BacklogItem
```

In `Services/APIClient.swift`, after the Projects extension (it ends after the private `patch`, `:2640`):

```swift
// MARK: - Backlog (G150) — the person's three writes

extension APIClient {
    func addBacklogItem(project: String, title: String, description: String) async throws -> BacklogItem {
        var body: [String: Any] = ["title": title]
        if !description.isEmpty { body["description"] = description }
        return try await post(Self.projectPath(project, "backlog"), body: body)
    }

    func addBacklogNote(project: String, item: String, note: String, status: String?) async throws -> BacklogItem {
        var body: [String: Any] = ["note": note]
        if let status { body["status"] = status }
        return try await post(Self.backlogPath(project, item, "notes"), body: body)
    }

    func updateBacklogItem(project: String, item: String, change: BacklogChange) async throws -> BacklogItem {
        try await patch(Self.backlogPath(project, item), body: change.body)
    }
}
```

(`post<T>` and the Projects extension's `patch<T>` are `private` in this file; a same-file extension of `APIClient`
may call them — which is why these three live here and not in `BacklogAPI.swift`.)

- [ ] **Step 5: Green.** `cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5` builds; `swift test --filter
  ProjectBacklogTests 2>&1 | tail -20` passes; then `swift test 2>&1 | tail -20` → 0 failures (the lints included:
  `RelativeDayTests`, `CountLiteralLintTests`, `ProjectBandTests`' "Timeline" lint, `FontLiteralLintTests`).

- [ ] **Step 6: Commit.**

```bash
cd <worktree> && git add app/CicadaApp/Sources/CicadaApp/Models/ProjectBacklog.swift \
  app/CicadaApp/Sources/CicadaApp/Services/BacklogAPI.swift \
  app/CicadaApp/Sources/CicadaApp/Views/Projects/BacklogCache.swift \
  app/CicadaApp/Sources/CicadaApp/Sync/BacklogMutations.swift app/CicadaApp/Sources/CicadaApp/Sync/SyncAPI.swift \
  app/CicadaApp/Sources/CicadaApp/Services/APIClient.swift app/CicadaApp/Sources/CicadaApp/Theme/Copy+Projects.swift \
  app/CicadaApp/Tests/CicadaAppTests/StoreTests.swift app/CicadaApp/Tests/CicadaAppTests/ProjectBacklogTests.swift \
  && git commit -m "feat(app): the backlog's wire, cache and writes, pure and tested (G150 R-B18, R-B19, R-B22; DR-21, DR-54, DR-58, DR-59)

BacklogList/BacklogItem decode the demo's wire leniently; BacklogModel decides
the tabs (Open · Doing · Done · All, dropped only under All), the default tab,
the age of the last note, the moves, and who wrote a note in words ('Claude
Code · Opus 5.5 · high effort' once the wire carries it). BacklogCache is
ProjectsCache's twin — in memory, ETag-revalidated, emptied on a bank switch —
and BacklogWrite paints only a status move, rolling it back with the server's
409 sentence.

<attribution lines>"
```

---

### Task 5: The Backlog section and the item card (G150 R-B19 … R-B24; DR-5, DR-16, DR-17, DR-18, DR-19, DR-20, DR-27, DR-28, DR-29, DR-31, DR-38, DR-39, DR-40, DR-41, DR-43, DR-44, DR-45, DR-48, DR-52, DR-54, DR-58, DR-60, DR-70)

The page: a Backlog section after Plan whose rows open the item as the third column, and the item card. Every
decision was made in Task 4; this task renders it and wires the slot.

**Files:**
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Projects/ProjectTrailing.swift` — the slot and the Esc order (pure)
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Projects/ProjectBacklogSection.swift`
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Projects/BacklogItemColumn.swift`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Projects/ProjectBand.swift:26` — `ProjectSection.backlog`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Projects/ProjectDetailColumn.swift` — two parameters, the section,
  `typing`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Projects/ProjectsPage.swift` — `card` becomes `trailing`
- Modify: `app/CicadaApp/Sources/CicadaApp/CicadaApp.swift:45, 156` and `ContentView.swift:49, 90-95` — inject and
  reset `BacklogCache`
- Modify: `app/CicadaApp/Tests/CicadaAppTests/SelectionTintLintTests.swift:7-14` — the two new view files
- Test: `app/CicadaApp/Tests/CicadaAppTests/ProjectBacklogViewTests.swift` (new)

**Interfaces:**
- Produces `ProjectTrailing` (`.entity`, `.backlogItem`, `entityId`, `backlogItemId`, `Step`,
  `escape(readerOpen:trailing:projectOpen:)`), `ProjectBacklogSection(projectId:today:openItem:writesBlocked:open:
  onEditingChange:)`, `BacklogItemColumn(projectId:itemId:onClose:onEscape:)`, `ProjectSection.backlog`, and
  `ProjectDetailColumn`'s new `openBacklogItem:` / `openItem:` parameters.
- Consumes Task 4's `BacklogCache`, `BacklogModel`, `BacklogWrite`, `BacklogChange`, `Copy.Projects.Backlog`, and
  the shared `DetailHeader`, `AdaptiveTextTabs`, `Tag`, `NeutralButton`, `TextButton`, `InlineLink`, `SectionLabel`,
  `MarkdownBody`, `ContributorAvatar`, `ListErrorCard`, `ListSkeleton`, `StoryRowSurface`, `ProjectWriteGate`,
  `Instant`, `RelativeDay`, `ISODay`.

- [ ] **Step 1: Failing tests.** Create `app/CicadaApp/Tests/CicadaAppTests/ProjectBacklogViewTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// G150 (R-B19, R-B21) — the page's one trailing slot, its Esc order, and where the Backlog section sits.
final class ProjectBacklogViewTests: XCTestCase {
    func testEscClosesTheReaderThenTheItemOrCardThenTheProject() {
        XCTAssertEqual(ProjectTrailing.escape(readerOpen: true, trailing: .backlogItem("RAP3"), projectOpen: true),
                       .reader)
        XCTAssertEqual(ProjectTrailing.escape(readerOpen: false, trailing: .backlogItem("RAP3"), projectOpen: true),
                       .trailing)
        XCTAssertEqual(ProjectTrailing.escape(readerOpen: false, trailing: .entity("hana-example"), projectOpen: true),
                       .trailing)
        XCTAssertEqual(ProjectTrailing.escape(readerOpen: false, trailing: nil, projectOpen: true), .project)
        XCTAssertEqual(ProjectTrailing.escape(readerOpen: false, trailing: nil, projectOpen: false), .nothing)
    }

    func testTheSlotHoldsOneThing() {
        XCTAssertEqual(ProjectTrailing.backlogItem("RAP3").backlogItemId, "RAP3")
        XCTAssertNil(ProjectTrailing.backlogItem("RAP3").entityId)
        XCTAssertEqual(ProjectTrailing.entity("hana-example").entityId, "hana-example")
        XCTAssertNil(ProjectTrailing.entity("hana-example").backlogItemId)
    }

    func testTheBacklogSitsAfterThePlanAndItsFoldIsRemembered() {
        XCTAssertEqual(ProjectSection.allCases, [.now, .lately, .plan, .backlog, .around])
        XCTAssertEqual(ProjectSection(rawValue: "backlog"), .backlog)
    }
}
```

In `SelectionTintLintTests.swift:7-14`, append `"Views/Projects/ProjectBacklogSection.swift",
"Views/Projects/BacklogItemColumn.swift"` to `scoped` (the lint fails vacuously-safe: a listed file that does not
exist yet is an `XCTUnwrap` failure — that is part of this task's red).

Run: `cd <worktree>/app/CicadaApp && swift build --build-tests 2>&1 | tail -5` → `ProjectTrailing` and
`ProjectSection.backlog` do not exist. That is the red.

- [ ] **Step 2: The slot.** Create `app/CicadaApp/Sources/CicadaApp/Views/Projects/ProjectTrailing.swift`:

```swift
import Foundation

/// G150 (R-B21) — what the Projects page's third column holds besides the Reader: an entity's card (R-PP17) or a
/// backlog item. One slot: opening one replaces the other, and the Reader, when open, wins it (DR-31).
enum ProjectTrailing: Equatable {
    case entity(String)
    case backlogItem(String)

    var entityId: String? {
        switch self {
        case .entity(let id): id
        case .backlogItem: nil
        }
    }

    var backlogItemId: String? {
        switch self {
        case .backlogItem(let id): id
        case .entity: nil
        }
    }

    /// DR-28 — what Esc (and DR-27's "‹ N projects") closes next: the Reader, then the item or card, then the project.
    enum Step: Equatable { case reader, trailing, project, nothing }

    static func escape(readerOpen: Bool, trailing: ProjectTrailing?, projectOpen: Bool) -> Step {
        if readerOpen { return .reader }
        if trailing != nil { return .trailing }
        return projectOpen ? .project : .nothing
    }
}
```

In `ProjectBand.swift:26`: `enum ProjectSection: String, CaseIterable, Sendable { case now, lately, plan, backlog,
around }` (raw values are what `cicada.projects.collapsed` stores; adding one moves none).

- [ ] **Step 3: The section.** Create `app/CicadaApp/Sources/CicadaApp/Views/Projects/ProjectBacklogSection.swift`:

```swift
import SwiftUI

/// G150 (R-B19) — a project's backlog, under Plan: text tabs Open · Doing · Done · All (DR-45; a dropped item shows
/// only under All, R-PP6's precedent), one row per item — its id (R-B24: the address people cite, never monospace,
/// DR-19), its title, a triage `Tag` and a "Paid AI" `Tag` (DR-44), the age of its last note (DR-58, the full date
/// in `.help`) — and "Add to backlog". A row opens the item as the third column (R-B21); the open one wears the
/// story's selected surface (`StoryRowSurface` — never the accent, DR-5). Its data is `BacklogCache` (R-B18): a line
/// while it reads, the error card with Retry, never a blank (DR-43).
struct ProjectBacklogSection: View {
    let projectId: String
    let today: ISODay
    let openItem: String?
    let writesBlocked: Bool
    let open: (String) -> Void
    /// R-PP23's rule — true while the add fields are open, so the column's L · M · D stand aside.
    var onEditingChange: (Bool) -> Void = { _ in }

    @Environment(BacklogCache.self) private var cache
    @Environment(Store.self) private var store
    @State private var tab: BacklogStatus? = .open
    /// Until the viewer picks a tab, the section follows `BacklogModel.defaultTab` as the list arrives (R-PP6).
    @State private var tabChosen = false
    @State private var adding = false
    @State private var newTitle = ""
    @State private var newWhy = ""
    @FocusState private var titleFocused: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            if let list = cache.list(projectId) {
                content(list)
            } else {
                switch cache.listPhase(projectId) {
                case .failed(let message):
                    ListErrorCard(title: Copy.Projects.Backlog.failedTitle, message: message) {
                        Task { await cache.refreshList(projectId) }
                    }
                case .gone:
                    line(Copy.Projects.Backlog.emptyAll)
                default:
                    line(Copy.Projects.Backlog.reading)
                }
            }
        }
        .task(id: projectId) { await cache.refreshList(projectId) }
        // `initial: true` — folding the section or switching projects rebuilds this view with the list already
        // cached, so a plain `onChange` would never fire and an all-done backlog would reopen on an empty Open.
        .onChange(of: cache.list(projectId).flatMap(BacklogModel.defaultTab), initial: true) { _, next in
            if !tabChosen, let next { tab = next }
        }
        .onChange(of: adding) { _, editing in onEditingChange(editing) }
        // Folding the section while the fields are open removes this view first (PJ-5's final-review reason).
        .onDisappear { onEditingChange(false) }
    }

    @ViewBuilder
    private func content(_ list: BacklogList) -> some View {
        let rows = BacklogModel.rows(list, tab: tab)
        AdaptiveTextTabs(tabs: BacklogModel.tabs(list), selection: tabBinding, menuTitle: Copy.Projects.Backlog.tabMenu)
            .padding(.bottom, CicadaTheme.spacingXS)
        if rows.isEmpty { line(BacklogModel.emptyLine(tab: tab)) }
        ForEach(rows) { row in rowView(row) }
        addRow
    }

    /// DR-45 / DR-60 — a tab switch is instant.
    private var tabBinding: Binding<BacklogStatus?> {
        Binding(get: { tab }, set: { next in
            Instant.run {
                tab = next
                tabChosen = true
            }
        })
    }

    private func line(_ text: String) -> some View {
        Text(text)
            .font(CicadaTheme.bodyFont)
            .foregroundStyle(CicadaTheme.textTertiary)
            .padding(.horizontal, CicadaTheme.spacingMD)
    }

    private func rowView(_ row: BacklogItemSummary) -> some View {
        let selected = openItem == row.id
        let age = BacklogModel.age(row, today: today)
        return Button { open(row.id) } label: {
            HStack(spacing: CicadaTheme.spacingMD) {
                Text(row.id)
                    .font(CicadaTheme.metaFont)
                    .monospacedDigit()
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .frame(minWidth: CicadaTheme.scaled(44), alignment: .leading)
                Text(row.title)
                    .font(CicadaTheme.rowFont)
                    .foregroundStyle(row.backlogStatus == .dropped ? CicadaTheme.textTertiary : CicadaTheme.textPrimary)
                    .lineLimit(1)
                if let triage = BacklogModel.triageLabel(row.triage) { Tag(text: triage) }
                if row.paid { Tag(text: Copy.Projects.Backlog.paid) }
                Spacer(minLength: CicadaTheme.spacingSM)
                if tab == nil {
                    Text(BacklogModel.statusLabel(row.backlogStatus))
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
                Text(age.text)
                    .font(CicadaTheme.metaFont)
                    .monospacedDigit()
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .help(age.help)
            }
            .modifier(StoryRowSurface(selected: selected))
        }
        .buttonStyle(.cicadaPlain)
        .help(Copy.Projects.Backlog.rowHelp(row.id))
        .accessibilityLabel(BacklogModel.accessibilityLabel(row, today: today))
        .accessibilityAddTraits(selected ? [.isSelected] : [])
        .id("backlog:\(row.id)")
    }

    @ViewBuilder
    private var addRow: some View {
        if adding {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                TextField(Copy.Projects.Backlog.titlePlaceholder, text: $newTitle)
                    .textFieldStyle(.roundedBorder)
                    .focused($titleFocused)
                    .onSubmit(submit)
                    .onExitCommand { cancel() }
                    .accessibilityLabel(Copy.Projects.Backlog.titleLabel)
                TextField(Copy.Projects.Backlog.descriptionPlaceholder, text: $newWhy, axis: .vertical)
                    .textFieldStyle(.roundedBorder)
                    .lineLimit(2...6)
                    .onExitCommand { cancel() }
                    .accessibilityLabel(Copy.Projects.Backlog.descriptionLabel)
                HStack(spacing: CicadaTheme.spacingSM) {
                    Spacer(minLength: 0)
                    TextButton(title: Copy.Projects.cancel) { cancel() }
                    NeutralButton(title: Copy.Projects.add, size: .compact,
                                  isDisabled: writesBlocked || newTitle.trimmingCharacters(in: .whitespaces).isEmpty,
                                  help: Copy.Projects.Backlog.addHelp,
                                  disabledHelp: writesBlocked ? Copy.Projects.sleepRunningHelp
                                                              : Copy.Projects.Backlog.titleLabel) {
                        submit()
                    }
                }
            }
            .frame(maxWidth: CicadaTheme.scaled(ColumnLayout.questionMaxWidth))
            .padding(.horizontal, CicadaTheme.spacingMD)
        } else {
            TextButton(title: Copy.Projects.Backlog.add, help: Copy.Projects.Backlog.addHelp) {
                adding = true
                DispatchQueue.main.async { titleFocused = true }
            }
            .disabled(writesBlocked)
            .padding(.leading, CicadaTheme.scaled(2))
        }
    }

    /// The person's add (R-B22: nothing painted — the id is the server's), then the new item opens beside the
    /// project.
    private func submit() {
        let title = newTitle.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !title.isEmpty, !writesBlocked else { return }
        let why = newWhy.trimmingCharacters(in: .whitespacesAndNewlines)
        cancel()
        Task {
            let write = BacklogWrite(projectId: projectId, action: .add(title: title, description: why), cache: cache)
            let ok = await store.perform(write)
            await cache.refreshList(projectId)
            if ok, let item = write.result { open(item.id) }
        }
    }

    private func cancel() {
        adding = false
        newTitle = ""
        newWhy = ""
    }
}
```

- [ ] **Step 4: The item card.** Create `app/CicadaApp/Sources/CicadaApp/Views/Projects/BacklogItemColumn.swift`:

```swift
import AppKit
import SwiftUI

/// G150 (R-B20, R-B21) — one backlog item as the Projects page's third column: its title as the detail heading
/// (`DetailHeader`, DR-16's H1 role — no new `displayFont` call site, DR-17) with who added it and when; its state,
/// triage and "Paid AI" as `Tag`s (DR-44); the moves it can make and "Edit title" (DR-40; disabled with the reason
/// while Sleep writes, DR-41); the Description and every note as page prose — `MarkdownBody`, because a note is a
/// written document, not words said in a conversation, so not DR-18's quote face; each note signed with its author's
/// real mark and words (DR-52, R-B6); the links; and "Add a note". Esc closes it (DR-28). It draws its own column
/// edge and is never blank (DR-43). The id and the file are in `.help` (R-B24).
struct BacklogItemColumn: View {
    let projectId: String
    let itemId: String
    let onClose: () -> Void
    let onEscape: () -> Void

    @Environment(BacklogCache.self) private var cache
    @Environment(Store.self) private var store
    @State private var note = ""
    @State private var renaming = false
    @State private var newTitle = ""
    @FocusState private var titleFocused: Bool
    /// R-PP5's rule — the viewer's today; midnight re-words the notes' days with no network.
    @State private var today = ISODay.today()

    /// R-PP20 / R-B8 — while Sleep writes, every write control waits, its reason in `.help` (DR-41).
    private var blocked: Bool { ProjectWriteGate.blocked(store.status.value) }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if let item = cache.item(projectId, itemId) {
                content(item)
            } else {
                header(title: itemId, blurb: nil, help: itemId)
                switch cache.itemPhase(projectId, itemId) {
                case .gone:
                    Text(Copy.Projects.Backlog.gone)
                        .font(CicadaTheme.detailBodyFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                case .failed(let message):
                    ListErrorCard(title: Copy.Projects.Backlog.itemFailedTitle, message: message) {
                        Task { await cache.refreshItem(projectId, itemId) }
                    }
                default:
                    ListSkeleton(message: Copy.Projects.Backlog.readingItem)
                }
                Spacer(minLength: 0)
            }
        }
        .padding(.horizontal, CicadaTheme.scaled(28))
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(CicadaTheme.bgBase)
        .columnEdge()
        .focusable()
        .focusEffectDisabled()
        .onExitCommand { if renaming { renaming = false } else { onEscape() } }
        .task(id: BacklogCache.key(projectId, itemId)) { await cache.refreshItem(projectId, itemId) }
        .onReceive(NotificationCenter.default.publisher(for: .NSCalendarDayChanged)) { _ in today = ISODay.today() }
    }

    @ViewBuilder
    private func content(_ item: BacklogItem) -> some View {
        let s = item.summary
        header(title: s.title, blurb: BacklogModel.addedLine(s, today: today),
               help: Copy.Projects.Backlog.itemHelp(s.id, path: item.path))
        ScrollView {
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(22)) {
                tags(s)
                actions(item)
                if renaming { renameRow }
                block(Copy.Projects.Backlog.description) {
                    if item.descriptionText.isEmpty {
                        faint(Copy.Projects.Backlog.noDescription)
                    } else {
                        MarkdownBody(text: item.descriptionText)
                    }
                }
                block(Copy.Projects.Backlog.notesTitle(item.notes.count)) {
                    if item.notes.isEmpty { faint(Copy.Projects.Backlog.noNotes) }
                    ForEach(Array(item.notes.enumerated()), id: \.offset) { _, n in noteRow(n) }
                }
                if !item.links.isEmpty {
                    block(Copy.Projects.Backlog.links) {
                        ForEach(item.links, id: \.self) { link in linkRow(link) }
                    }
                }
                noteField
            }
            .frame(maxWidth: CicadaTheme.scaled(ProjectLayout.textMaxWidth), alignment: .leading)
            .padding(.bottom, CicadaTheme.scaled(48))
        }
    }

    private func header(title: String, blurb: String?, help: String) -> some View {
        DetailHeader(title: title, blurb: blurb, closeHelp: Copy.Projects.Backlog.closeHelp, onClose: onClose) {
            Image(systemName: "checklist")
                .font(CicadaTheme.icon(.list))
                .foregroundStyle(CicadaTheme.textTertiary)
        }
        .help(help)
    }

    private func tags(_ s: BacklogItemSummary) -> some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            Tag(text: BacklogModel.statusLabel(s.backlogStatus))
            if let triage = BacklogModel.triageLabel(s.triage) { Tag(text: triage) }
            if s.paid { Tag(text: Copy.Projects.Backlog.paid) }
        }
    }

    private func actions(_ item: BacklogItem) -> some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            ForEach(BacklogModel.moves(from: item.summary.backlogStatus), id: \.self) { to in
                NeutralButton(title: BacklogModel.moveLabel(to), size: .compact, isDisabled: blocked,
                              help: BacklogModel.moveHelp(to), disabledHelp: Copy.Projects.sleepRunningHelp) {
                    Task { await write(.update(item: itemId, change: BacklogChange(status: to.rawValue))) }
                }
            }
            TextButton(title: Copy.Projects.Backlog.editTitle, help: Copy.Projects.Backlog.editTitleHelp) {
                newTitle = item.summary.title
                renaming = true
                DispatchQueue.main.async { titleFocused = true }
            }
            .disabled(blocked)
        }
    }

    private var renameRow: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            TextField(Copy.Projects.Backlog.titleLabel, text: $newTitle)
                .textFieldStyle(.roundedBorder)
                .focused($titleFocused)
                .onSubmit { submitTitle() }
                .onExitCommand { renaming = false }
                .accessibilityLabel(Copy.Projects.Backlog.titleLabel)
            TextButton(title: Copy.Projects.cancel) { renaming = false }
            NeutralButton(title: Copy.Projects.Backlog.saveTitle, size: .compact,
                          isDisabled: blocked || newTitle.trimmingCharacters(in: .whitespaces).isEmpty,
                          help: Copy.Projects.Backlog.editTitleHelp,
                          disabledHelp: blocked ? Copy.Projects.sleepRunningHelp : Copy.Projects.Backlog.titleLabel) {
                submitTitle()
            }
        }
    }

    private func block<Body: View>(_ title: String, @ViewBuilder body: () -> Body) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            SectionLabel(title)
            body()
        }
    }

    private func faint(_ text: String) -> some View {
        Text(text).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textTertiary)
    }

    /// R-B6 — the author's real mark (DR-52) and words, the day in `RelativeDay`'s words (DR-58, full date in `.help`),
    /// then the note as page prose.
    private func noteRow(_ n: BacklogNote) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            HStack(spacing: CicadaTheme.spacingSM) {
                ContributorAvatar(author: n.by, kind: n.byKind, provider: n.byProvider, size: CicadaTheme.scaled(16))
                Text(BacklogModel.authorLine(n))
                    .font(CicadaTheme.metaMediumFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                if let day = ISODay(n.day) {
                    Text(RelativeDay.phrase(day, today: today))
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .help(RelativeDay.full(day))
                }
            }
            MarkdownBody(text: n.text)
                .padding(.leading, CicadaTheme.scaled(24))
        }
        .accessibilityElement(children: .combine)
    }

    @ViewBuilder
    private func linkRow(_ link: BacklogLink) -> some View {
        if link.kind == "url", let url = URL(string: link.ref), url.scheme?.hasPrefix("http") == true {
            InlineLink(title: link.ref, help: link.ref) { NSWorkspace.shared.open(url) }
        } else {
            Text(link.kind == "pr" ? Copy.Projects.Backlog.pullRequest(link.ref) : link.ref)
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .textSelection(.enabled)
        }
    }

    private var noteField: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            SectionLabel(Copy.Projects.Backlog.addNote)
            TextField(Copy.Projects.Backlog.notePlaceholder, text: $note, axis: .vertical)
                .textFieldStyle(.roundedBorder)
                .lineLimit(2...8)
                .accessibilityLabel(Copy.Projects.Backlog.addNote)
            HStack {
                Spacer(minLength: 0)
                NeutralButton(title: Copy.Projects.Backlog.saveNote, size: .compact,
                              isDisabled: blocked || note.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                              help: Copy.Projects.Backlog.saveNoteHelp,
                              disabledHelp: blocked ? Copy.Projects.sleepRunningHelp
                                                    : Copy.Projects.Backlog.notePlaceholder) {
                    let text = note.trimmingCharacters(in: .whitespacesAndNewlines)
                    note = ""
                    Task { await write(.note(item: itemId, text: text, status: nil)) }
                }
            }
        }
        .frame(maxWidth: CicadaTheme.scaled(ColumnLayout.questionMaxWidth))
    }

    private func submitTitle() {
        let title = newTitle.trimmingCharacters(in: .whitespacesAndNewlines)
        renaming = false
        guard !title.isEmpty, !blocked, title != cache.item(projectId, itemId)?.summary.title else { return }
        Task { await write(.update(item: itemId, change: BacklogChange(title: title))) }
    }

    /// R-B22 — every write goes through `Store.perform`, then the cache asks again for what the server now holds (a
    /// 304 costs nothing).
    private func write(_ action: BacklogWrite.Action) async {
        _ = await store.perform(BacklogWrite(projectId: projectId, action: action, cache: cache))
        await cache.refreshItem(projectId, itemId)
        await cache.refreshList(projectId)
    }
}
```

- [ ] **Step 5: Wire the column and the page.** In `ProjectDetailColumn.swift`:
  - add `let openBacklogItem: String?` after `let openCard: String?` (`:15`) and `let openItem: (String) -> Void`
    after `let openEntity` (`:20`);
  - add `@Environment(BacklogCache.self) private var backlogCache` with the other environment values, and
    `/// G150 — the backlog's add fields are open, so a letter is typing, not a key.` /
    `@State private var backlogEditing = false` beside `planEditing`;
  - `typing` becomes `logFocused || planEditing || backlogEditing`;
  - in the column's `.task(id: projectId)` (`:98-101`), after `await cache.refreshTimeline(projectId)`, add:

```swift
            // R-B19 — a folded Backlog section still says "n open": `section(_:…)` builds its body only when open,
            // so the section's own `.task` never runs while it is folded.
            await backlogCache.refreshList(projectId)
```

  - right after `.id("section.plan")` (`:171`):

```swift
        // G150 (R-B19) — after Plan: the plan is what is dated, the backlog what is kept for later.
        section(.backlog, title: Copy.Projects.Backlog.title,
                meta: backlogCache.list(projectId).map { Copy.Projects.Backlog.openCount(BacklogModel.openCount($0)) }
                    ?? "") {
            ProjectBacklogSection(projectId: projectId, today: today, openItem: openBacklogItem, writesBlocked: blocked,
                                  open: openItem, onEditingChange: { backlogEditing = $0 })
        }
        .id("section.backlog")
```

  In `ProjectsPage.swift`:
  - `:24-25` — replace `/// R-PP17 — an entity's card in the third column; the Reader wins the slot.` /
    `@State private var card: String?` with `/// R-PP17 / R-B21 — the third column's one slot besides the Reader: an
    entity's card or a backlog item.` / `@State private var trailing: ProjectTrailing?`, and add
    `@Environment(BacklogCache.self) private var backlogCache` with the other environment values.
  - `hasTrailing: provenance.isPresented || card != nil` → `hasTrailing: provenance.isPresented || trailing != nil`.
  - The `ProjectDetailColumn(...)` call: `openCard: card,` → `openCard: trailing?.entityId, openBacklogItem:
    trailing?.backlogItemId,` and add `openItem: { openItem($0) }` after `openEntity: { openCard($0) }`.
  - The `trailing:` builder (`:80-89`) becomes:

```swift
        } trailing: { _ in
            if provenance.isPresented {
                ReaderColumn().focused($focus, equals: .reader)
            } else if let card = trailing?.entityId {
                ProjectEntityColumn(entityId: card, openProject: { openProject($0) }, onClose: { closeTrailing() },
                                    onEscape: { escape() })
                    .id(card)
                    .focused($focus, equals: .reader)
            } else if let item = trailing?.backlogItemId, let project = openId {
                BacklogItemColumn(projectId: project, itemId: item, onClose: { closeTrailing() },
                                  onEscape: { escape() })
                    .id(BacklogCache.key(project, item))
                    .focused($focus, equals: .reader)
            }
        }
```

  - The `store.version` observer (`:103-110`) becomes:

```swift
        // R-PP3 / R-B18 — a sync version event that moved what an ETag folds asks again (a 304 costs nothing).
        .onChange(of: store.version) { old, new in
            let projects = ProjectsRefresh.shouldRevalidate(old: old, new: new)
            let backlog = BacklogRefresh.shouldRevalidate(old: old, new: new)
            guard projects || backlog else { return }
            Task {
                if projects {
                    await cache.refreshList()
                    if let id = columns.openId { await cache.refreshTimeline(id) }
                }
                if backlog, let id = columns.openId {
                    await backlogCache.refreshList(id)
                    if let item = trailing?.backlogItemId { await backlogCache.refreshItem(id, item) }
                }
            }
        }
```

  - In the bank observer (`:111-114`), `openProject` (`:139-151`), `move` (`:153-160`) and `closeProject`
    (`:175-182`): `card = nil` → `trailing = nil`.
  - `escape()` (`:160-171`) becomes:

```swift
    /// DR-28 — Esc closes the rightmost open thing: the Reader, then the item or card, then the project.
    private func escape() {
        Instant.run {
            switch ProjectTrailing.escape(readerOpen: provenance.isPresented, trailing: trailing,
                                          projectOpen: columns.openId != nil) {
            case .reader: provenance.close()
            case .trailing: trailing = nil
            case .project:
                columns.close()
                focus = .list
            case .nothing: break
            }
        }
    }
```

  - `openCard` (`:184-188`): `card = id` → `trailing = .entity(id)`; `closeCard` becomes
    `private func closeTrailing() { trailing = nil }`; and add:

```swift
    /// R-B21 — a backlog row opens its item in the same slot; a Reader the old selection opened steps aside (DR-29).
    private func openItem(_ id: String) {
        trailing = .backlogItem(id)
        if provenance.isPresented { provenance.close() }
    }
```

  - `showList` (`:193-198`): `else if card != nil { card = nil }` → `else if trailing != nil { trailing = nil }`.

  In `CicadaApp.swift`, after `@State private var projectsCache = ProjectsCache()` (`:45`): `/// G150 (R-B18) — the
  Backlog section's in-memory cache; app-level for ProjectsCache's reason.` / `@State private var backlogCache =
  BacklogCache()`, and `.environment(backlogCache)` after `.environment(projectsCache)` (`:156`). In `ContentView.swift`,
  `@Environment(BacklogCache.self) private var backlogCache` after the `ProjectsCache` one (`:49`), and
  `backlogCache.reset()` after `projectsCache.reset()` in the bank observer (`:93`), its comment extended with "— and
  the backlog's: item ids repeat across banks (R-B18)".

- [ ] **Step 6: Green.** `cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5` builds; `swift test --filter
  "ProjectBacklog|SelectionTintLint|RelativeDay|ProjectBand|CountLiteralLint|FontLiteralLint|SectionLabelLint" 2>&1 |
  tail -20` passes; then `swift test 2>&1 | tail -20` → 0 failures; `cd <worktree> && node --test
  app/CicadaApp/Tests/graph/*.test.js` → 8/8.

- [ ] **Step 7: Commit.**

```bash
cd <worktree> && git add app/CicadaApp/Sources/CicadaApp/Views/Projects/ProjectTrailing.swift \
  app/CicadaApp/Sources/CicadaApp/Views/Projects/ProjectBacklogSection.swift \
  app/CicadaApp/Sources/CicadaApp/Views/Projects/BacklogItemColumn.swift \
  app/CicadaApp/Sources/CicadaApp/Views/Projects/ProjectBand.swift \
  app/CicadaApp/Sources/CicadaApp/Views/Projects/ProjectDetailColumn.swift \
  app/CicadaApp/Sources/CicadaApp/Views/Projects/ProjectsPage.swift app/CicadaApp/Sources/CicadaApp/CicadaApp.swift \
  app/CicadaApp/Sources/CicadaApp/ContentView.swift app/CicadaApp/Tests/CicadaAppTests/SelectionTintLintTests.swift \
  app/CicadaApp/Tests/CicadaAppTests/ProjectBacklogViewTests.swift \
  && git commit -m "feat(app): a project's Backlog section and the item card (G150 R-B19…R-B24; DR-5, DR-16, DR-17, DR-18, DR-19, DR-20, DR-27, DR-28, DR-29, DR-31, DR-38, DR-39, DR-40, DR-41, DR-43, DR-44, DR-45, DR-48, DR-52, DR-54, DR-58, DR-60, DR-70)

After Plan: text tabs Open · Doing · Done · All, rows with the id, the title, a
triage tag and the age of the last note, and Add to backlog. A row opens the
item in the third column — the title as the heading, state and triage as tags,
the moves (Start · Mark done · Drop · Reopen) and Edit title, the description
and every note as page prose signed with its author's real mark, the links, and
Add a note. The slot is one (Reader, else the item or the card); Esc closes
them in that order.

<attribution lines>"
```

---

### Task 6: ⌘K finds backlog items (G150 R-B25; DR-60)

A new FTS kind and `/search` kind on the server, a "Backlog" group in the palette, and a landing that opens Projects
with the item in the third column.

**Files:**
- Modify: `api/services/search_index.py` — `SCHEMA_VERSION` (`:69`), the `blg` table (`:92-107`), `_scan`
  (`:228-235`), `_ordered` (`:245-255`), `_index_backlog`, `_INDEXERS` (`:491`)
- Modify: `api/services/search_service.py` — `KINDS` / `_KIND_ALIASES` (`:44-51`), `_backlog_kind`,
  `_search_indexed` (`:636-664`)
- Test: `api/tests/test_backlog_search.py` (new); the pin moved in `api/tests/test_search_service.py:147` (an
  all-kinds search's totals now carry `backlog` too)
- Modify: `app/CicadaApp/Sources/CicadaApp/Search/FindModels.swift` (`:10-12`, `:24-59`, `:97-113`),
  `Search/FindServerRows.swift` (`:6`, `:8-16`, `:22-28`, `:43-104`), `Search/FindMerge.swift` (`:94-178`),
  `Search/FindPaletteModel.swift` (`:239-240`), `Support/AppRouter.swift` (`:76-92`), `ContentView.swift`
  (`:357-359`), `Views/Projects/ProjectsPage.swift` (`openPendingProject`)
- Test: append to `app/CicadaApp/Tests/CicadaAppTests/FindServerTests.swift` and `AppRouterTests.swift`

**Interfaces:**
- Produces the `/search` kind `backlog` (a hit: `id` = item id, `name` = title, `type` = triage or `backlog`,
  `status`, `subjectId` = project, `timestamp` = `updated`); `FindKind.backlog`, `FindGroupID.backlog`,
  `FindDestination.backlogItem(project:id:)`, `FindServerRows.Context.projectName`, `AppRouter.routeToBacklogItem`
  / `pendingBacklogItem` / `consumeBacklogItem`.
- Consumes Task 1's `backlog.parse_body`, Task 4's `BacklogModel`, Task 5's `ProjectTrailing`.

- [ ] **Step 1: Failing tests.** Create `api/tests/test_backlog_search.py`:

```python
"""G150 (R-B25) — ⌘K finds backlog items by title, id and a note's words; a dropped item ranks after every live
one. Synthetic only."""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from _synthetic_bank import _bank
from api import config, main
from api.services import backlog, bank_index, search_index, search_service

NOW = datetime(2026, 9, 24, 10, tzinfo=timezone.utc)


@pytest.fixture
def bank(tmp_path):
    memory = _bank(tmp_path, git=False)
    bank_index.invalidate()
    search_index.reset()
    backlog.add_item(memory, project="alpha-project", title="Cache the timeline", description="Big projects are slow.",
                     triage="apply", author="user", now=NOW, tz_name="UTC")
    backlog.add_item(memory, project="alpha-project", title="Cache the graph layout", description="An old idea.",
                     author="user", now=NOW, tz_name="UTC")
    backlog.update_item(memory, project="alpha-project", item="AP2", status="dropped", author="user", now=NOW,
                        tz_name="UTC")
    backlog.add_note(memory, project="alpha-project", item="AP1", note="The bottleneck is page parsing.",
                     author="claude-code", now=NOW, tz_name="UTC")
    search_index.ensure_fresh(memory, wait=True, max_age_s=0)
    return memory


def _hits(bank, q):
    return search_service.search(bank, q, kinds=["backlog"], mode="prefix").results


def test_an_item_is_found_by_its_title_its_id_and_its_notes(bank):
    hit = _hits(bank, "timeline")[0]
    assert (hit.id, hit.name, hit.status, hit.type, hit.subject_id, hit.kind) == (
        "AP1", "Cache the timeline", "open", "apply", "alpha-project", "backlog")
    assert hit.timestamp == "2026-09-24"
    assert [h.id for h in _hits(bank, "ap1")] == ["AP1"]
    assert [h.id for h in _hits(bank, "bottleneck")] == ["AP1"]


def test_a_dropped_item_ranks_after_every_live_one_and_the_total_is_exact(bank):
    result = search_service.search(bank, "cache", kinds=["backlog"], mode="prefix")
    assert [h.id for h in result.results] == ["AP1", "AP2"]
    assert result.totals["backlog"] == 2
    assert search_service.parse_kinds("entity,backlog") == ["entity", "backlog"]


def test_the_search_route_takes_the_backlog_kind(bank, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    try:
        body = TestClient(main.app).get("/search", params={"q": "timeline", "kinds": "entity,backlog",
                                                           "mode": "prefix"}).json()
    finally:
        config.get_settings.cache_clear()
    assert any(r["kind"] == "backlog" and r["id"] == "AP1" and r["subjectId"] == "alpha-project"
               for r in body["results"])


def test_the_schema_bump_rebuilds_every_index_once():
    assert search_index.SCHEMA_VERSION == "4" and "blg" in search_index.WEIGHTS
```

Append to `FindServerTests` (inside the class):

```swift
    /// G150 (R-B25) — a backlog hit is a row of its own group that lands on Projects with the item open.
    func testABacklogHitLandsOnProjectsWithTheItemOpen() {
        let response = FakeFindSearch.decode(#"""
        {"results": [{"id": "RAP3", "name": "Swap the gripper camera for a global-shutter one", "type": "research",
          "status": "open", "confidence": 0, "score": 3, "snippet": "", "kind": "backlog",
          "subjectId": "rover-arm-project", "timestamp": "2026-09-20"}],
         "totals": {"backlog": 1}, "mode": "prefix", "indexState": "ready"}
        """#)
        var c = context
        c.projectName = { $0 == "rover-arm-project" ? "Rover Arm Project" : nil }
        let rows = FindServerRows.rows(response, query: "camera", context: c)
        XCTAssertEqual(rows.count, 1)
        let row = rows[0]
        XCTAssertEqual(row.group, .backlog)
        XCTAssertEqual(row.key, FindRowKey(kind: .backlog, id: "rover-arm-project/RAP3"))
        XCTAssertEqual(row.detail, "RAP3 · Rover Arm Project · Open")
        XCTAssertEqual(row.badge, "Research")
        XCTAssertEqual(row.destination, .backlogItem(project: "rover-arm-project", id: "RAP3"))
        XCTAssertEqual(FindServerRows.totals(response, rows: rows, kinds: FindServerRows.kinds, perKind: 5)[.backlog],
                       .exact(1))
        XCTAssertTrue(FindServerRows.kinds.contains("backlog"))
        XCTAssertTrue(FindGroupID.inbox < FindGroupID.backlog && FindGroupID.backlog < FindGroupID.settings)
        XCTAssertEqual(FindRowText.primaryVerb(row.destination), "Open in Projects")
        XCTAssertEqual(FindRowText.kindLabel(row), "Backlog item")
    }
```

Append to `AppRouterTests` (inside the class):

```swift
    /// G150 (R-B25) — a palette landing carries the item to the Projects page with its project, read-then-clear.
    func testABacklogLandingCarriesTheItemWithItsProject() {
        let router = AppRouter()
        router.routeToBacklogItem(project: "rover-arm-project", item: "RAP3")
        XCTAssertEqual(router.pendingTab, .projects)
        XCTAssertEqual(router.consumeProject(), "rover-arm-project")
        XCTAssertEqual(router.consumeBacklogItem(), "RAP3")
        XCTAssertNil(router.consumeBacklogItem(), "read-then-clear")
    }
```

Move the one pin this task changes on purpose: `api/tests/test_search_service.py:147` —
`assert set(resp.totals) == {"entity", "claim", "episode", "media", "inbox"}` becomes
`assert set(resp.totals) == set(search_service.KINDS)` (an all-kinds search now reports a `backlog` total, 0 on that
bank).

Run: `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_backlog_search.py -q -p no:cacheprovider` → no
backlog hits and `SCHEMA_VERSION == "3"`; `cd <worktree>/app/CicadaApp && swift build --build-tests 2>&1 | tail -5`
→ `FindGroupID.backlog` does not exist. That is the red.

- [ ] **Step 2: The index.** In `api/services/search_index.py`:
  - `SCHEMA_VERSION = "4"` with the comment `# "4": G150 — backlog items are their own kind (`blg`); the bump rebuilds
    every index once (TODO ruling 3).` after the `"3"` comment.
  - After `INDEXED_SUBDIRS`:

```python
# G150 (R-B25): one folder per project under `backlog/`, one file per item —
# ordered after everything else, so a full build hands items the largest ids.
BACKLOG_SUBDIR = "backlog"
_ORDER = (*INDEXED_SUBDIRS, BACKLOG_SUBDIR)
```

  - `_FTS_COLUMNS` gains `"blg": "title, aliases, keywords, body",` and `WEIGHTS` gains `"blg": "10.0, 9.0, 7.0,
    4.0",` (title, the id as its alias, project + state + triage as keywords, the description and notes as body —
    QuickMatch's weights ×10, like the others).
  - `_scan` — before `return out`:

```python
    root = Path(memory_path) / BACKLOG_SUBDIR
    if root.is_dir():
        for folder in sorted(p for p in root.iterdir() if p.is_dir()):
            for f in bank_index.files(memory_path, f"{BACKLOG_SUBDIR}/{folder.name}"):
                out[f"{BACKLOG_SUBDIR}/{folder.name}/{f.path.name}"] = f
```

  - `_ordered`'s key: `INDEXED_SUBDIRS.index(subdir)` → `_ORDER.index(subdir)`.
  - After `_index_inbox`:

```python
def _index_backlog(conn, doc_key: str, f, fm: dict, body: str) -> None:
    """G150 (R-B25): an item is found by its title, by its id (so "RAP3" or
    "G13" lands on it), by its project, state and triage, and by the words of
    its description and notes. `ref` is `<project>/<id>` — the address the
    palette opens."""
    from api.services import backlog

    project, iid = doc_key.split("/")[1], f.path.stem
    meta = {"id": iid, "project": project, "title": str(fm.get("title") or iid),
            "status": str(fm.get("status") or "open"), "triage": str(fm.get("triage") or "") or None,
            "updated": str(fm.get("updated") or fm.get("created") or "")[:10] or None}
    description, notes = backlog.parse_body(body)
    text = "\n".join([description, *(n[2] for n in notes)])[:BODY_CHARS]
    doc_id = _insert_doc(conn, doc_key, "backlog", f"{project}/{iid}", f, meta)
    conn.execute(
        "INSERT INTO blg(rowid, title, aliases, keywords, body) VALUES (?, ?, ?, ?, ?)",
        (doc_id << ROW_BITS, meta["title"], iid,
         " ".join(x for x in (project, meta["status"], meta["triage"]) if x), text),
    )
```

  - `_INDEXERS` gains `"backlog": _index_backlog`.

  In `api/services/search_service.py`: `KINDS = ("entity", "claim", "episode", "media", "inbox", "backlog")`;
  `_KIND_ALIASES` gains `"backlog": "backlog", "task": "backlog", "tasks": "backlog",`; a scan constant beside
  `INBOX_SCAN`: `BACKLOG_SCAN = 200`; after `_inbox_kind`:

```python
def _backlog_kind(ctx: _Ctx) -> tuple[list[SearchHit], int | None]:
    """G150 (R-B25): backlog items, ranked like the inbox — QuickMatch tiers
    over title, id and keywords, then bm25 — with a dropped item after every
    live one. The palette groups them as "Backlog" and opens the item."""
    rows = ctx.reader.ranked("blg", ctx.match, BACKLOG_SCAN)
    docs = ctx.reader.docs([d for d, _ in rows])
    ranked: list[tuple[tuple, SearchHit]] = []
    for doc_id, bm in rows:
        doc = docs.get(doc_id)
        if doc is None:
            continue
        meta = doc.meta
        keywords = " ".join(x for x in (meta.get("project"), meta.get("status"), meta.get("triage")) if x)
        fields = [(meta.get("title", ""), 1.0, "name"), (meta.get("id", ""), 0.9, "alias"), (keywords, 0.7, "keyword")]
        score, label = quick_score(ctx.tokens, fields)
        snippet, offsets = snippet_window(meta.get("title", ""), ctx.tokens)
        hit = SearchHit(
            id=meta.get("id") or doc.ref, name=meta.get("title") or doc.ref, type=meta.get("triage") or "backlog",
            status=meta.get("status") or "open", confidence=0.0, score=score, snippet=snippet, kind="backlog",
            snippet_offsets=offsets, matched_field=label, subject_id=meta.get("project") or None,
            timestamp=meta.get("updated"),
        )
        ranked.append(((meta.get("status") == "dropped", -score, bm), hit))
    ranked.sort(key=lambda r: r[0])
    total = len(ranked) if len(rows) < BACKLOG_SCAN else None
    return [hit for _k, hit in ranked][: ctx.per_kind], total
```

  and in `_search_indexed`, after the inbox branch:

```python
    if "backlog" in ctx.kinds and tokens:
        out["backlog"], total = _backlog_kind(ctx)
        if total is not None:
            totals["backlog"] = total
```

- [ ] **Step 3: The palette.** In `Search/FindModels.swift`: `FindKind` gains `backlog` after `inbox`; `FindGroupID`
  becomes `case ask, topHit, recent, entities, conversations, beliefs, sources, inbox, backlog, settings, actions,
  askedBefore, suggested` (its raw values are only an order — recents persist `FindRowKey`, whose kind is a string),
  with `case .backlog: "Backlog"` in `title` and `case .backlog: "checklist"` in `glyph`; `FindDestination` gains
  `case backlogItem(project: String, id: String)` after `inbox(id:)`.

  In `Search/FindServerRows.swift`:
  - `static let kinds = ["entity", "claim", "episode", "media", "backlog"]` — and the doc comment adds "; `backlog`
    (G150) has no local tier — it is not a Store domain";
  - `group(forKind:)` gains `case "backlog": .backlog`;
  - `Context` gains `/// G150 — a project's name for a backlog row's detail line (the Store's entity names).` /
    `var projectName: (String) -> String? = { _ in nil }`;
  - the hit switch gains, before `default:`:

```swift
            case "backlog":
                // G150 (R-B25) — the id is the item's address (R-B24); the row lands on Projects with the item open.
                let project = hit.subjectId ?? ""
                let state = BacklogModel.statusLabel(BacklogStatus(rawValue: hit.status) ?? .open)
                rows.append(FindRow(key: FindRowKey(kind: .backlog, id: "\(project)/\(hit.id)"), group: .backlog,
                                    title: hit.name, titleRanges: bold(hit.name),
                                    detail: [hit.id, context.projectName(project) ?? project, state]
                                        .joined(separator: " · "),
                                    badge: BacklogModel.triageLabel(hit.type), mark: .symbol("checklist"),
                                    trailing: date(hit.timestamp), score: hit.score,
                                    destination: .backlogItem(project: project, id: hit.id)))
```

  In `Search/FindMerge.swift`: `kindLabel` gains `case .backlog: "Backlog item"`; `primaryVerb` gains
  `case .backlogItem: "Open in Projects"`.

  In `Search/FindPaletteModel.swift` `runPass`, after `context.mediaURL = …`:
  `let names = store.entityNames` / `context.projectName = { names.name(for: $0) }`.

  In `Support/AppRouter.swift`, after `consumeProject()`:

```swift
    /// G150 (R-B25) — a backlog item opened from ⌘K: Projects, its project open, the item in the third column. The
    /// item is set before the project, so the page's `pendingProject` observer finds both.
    var pendingBacklogItem: String?

    func routeToBacklogItem(project: String, item: String) {
        pendingBacklogItem = item
        routeToProject(project)
    }

    /// Read-then-clear, `consumeProject`'s reason.
    @discardableResult
    func consumeBacklogItem() -> String? {
        defer { pendingBacklogItem = nil }
        return pendingBacklogItem
    }
```

  In `ContentView.openFind` (`:357-359`), after the `.inbox` case:

```swift
        case .backlogItem(let project, let id):
            router.routeToBacklogItem(project: project, item: id)
```

  In `ProjectsPage.openPendingProject`, right after `columns.open(id)`:
  `if let item = router.consumeBacklogItem() { openItem(item) } else { trailing = nil }` — a backlog landing opens
  its item through Task 5's `openItem`, so a Reader left open steps aside (R-B21: the Reader otherwise wins the slot
  and the landed item would not show); any other ⌘K project landing closes a stale item or card.

- [ ] **Step 4: Green.** `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_backlog_search.py
  api/tests/test_search_service.py api/tests/test_search_index.py api/tests/test_maintenance_search_index.py
  api/tests/test_sleep_search_index.py api/tests/test_search_claims_about.py -q -p no:cacheprovider` passes, then the
  full backend suite: 0 failures. `cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5` builds and `swift test 2>&1 |
  tail -20` → 0 failures (re-run a search-latency test alone before calling it yours).

- [ ] **Step 5: Commit.**

```bash
cd <worktree> && git add api/services/search_index.py api/services/search_service.py api/tests/test_backlog_search.py \
  api/tests/test_search_service.py app/CicadaApp/Sources/CicadaApp/Search/FindModels.swift app/CicadaApp/Sources/CicadaApp/Search/FindServerRows.swift \
  app/CicadaApp/Sources/CicadaApp/Search/FindMerge.swift app/CicadaApp/Sources/CicadaApp/Search/FindPaletteModel.swift \
  app/CicadaApp/Sources/CicadaApp/Support/AppRouter.swift app/CicadaApp/Sources/CicadaApp/ContentView.swift \
  app/CicadaApp/Sources/CicadaApp/Views/Projects/ProjectsPage.swift \
  app/CicadaApp/Tests/CicadaAppTests/FindServerTests.swift app/CicadaApp/Tests/CicadaAppTests/AppRouterTests.swift \
  && git commit -m "feat(search): ⌘K finds backlog items and opens them in Projects (G150 R-B25; DR-60)

A derived FTS table 'blg' (title, the id as its alias, project/state/triage,
the description and notes; SCHEMA_VERSION 4 rebuilds every index once) and a
'backlog' /search kind, a dropped item after every live one. The palette's
Backlog group sits after Inbox; a row lands on Projects with its project open
and the item in the third column.

<attribution lines>"
```

---

### Task 7: Docs — G150, G13's pointer, CLAUDE.md, TODO.md, DESIGN_RULES §9 (the privacy rule; R-B19 … R-B24, R-B27)

The backlog row the owner asked for ("document this too for now in the backlog"), what CLAUDE.md now has to say, the
handoff line, and the dated §9 rulings. Docs only; no test changes.

**Files:**
- Modify: `docs/goals/memory-evolution.md` — a new row **G150** after G141 (`:705`); G13's row (`:483`) gains a pointer
- Modify: `CLAUDE.md` — a `### Backlogs (G150)` paragraph in the Storage Layer, and six touch-ups
- Modify: `docs/goals/TODO.md` — one "where things stand" paragraph and one open owner question
- Modify: `docs/design/DESIGN_RULES.md` — five dated lines at the end of §9's list

- [ ] **Step 1: The G150 row.** In `docs/goals/memory-evolution.md`, add this row on the line after G141's (G142–G149
  are reserved by other round-4 branches; the orchestrator orders the rows at merge):

```markdown
| G150 | **Backlogs live in memory — a project's backlog is first-class memory: filed by agents over MCP and by the person in the app, shown on the Projects page, found by ⌘K, every note signed** (Rodrigo 2026-09-24: "this back and forth where i tell an agent to put it in the backlog, that backlog itself i believe should go in cicada project memory, dont you think? with the brief task and an appended notes/description and maybe some other things that might be relevant to how we show and store them.") | **The problem.** "Put it in the backlog" meant an agent editing a markdown table in some repository — this file is the example — invisible to Cicada, to every other agent and to the person's own app, with nothing saying who added a row or a finding. **The design** (round 4; plan `docs/superpowers/plans/2026-09-24-r4-backlog-in-memory.md`, rulings R-B1…R-B27). One markdown file per item at `<bank>/backlog/<project-id>/<item-id>.md`: `id`, `title` (the brief task), `project`, `status` (open · doing · done · dropped), `triage` (apply · research · decide), `paid` (💸), `created`/`updated`, `added_by`, `session`, `links`, `order`, and a `notes: [{at, by, session}]` sidecar; `## Description` holds the reasoning and `## Notes` append-only `### <day> · <who>` entries — a status move is itself a signed note, and a note is edited only through git history. Never an entity page: never extracted, never decays, and the writer never touches `entities/`. Ids are `<PREFIX><n>` like G-ids — the page's `backlog_prefix:`, else the prefix the project's items share (an imported G-row list continues its sequence), else the name's initials (`Orchard` → `ORC`) — max+1 (G114), claimed by an exclusive create. **One writer**, `api/services/backlog.py`, behind REST (`GET/POST /projects/{id}/backlog`, `GET/PATCH /backlog/{project}/{item}`, `POST …/notes`, `POST /projects/{id}/backlog/import`; 409 while Sleep runs; `Cicada-Author: user`), MCP (`cicada_backlog` read; `cicada_add_backlog_item` and `cicada_add_backlog_note` record — the harness as author, the conversation as `Cicada-Session:`, refused while Sleep runs and in a demo bank; a remote connection without `sources` never reads the person's own words), the importer and the demo. Everything is scrubbed; a second open item for one idea is refused and pointed at the first. The contract (CONTRACT_VERSION 7) tells an agent to file the brief task and the reasoning when the person says "put it in the backlog", and later findings as notes on the same item; `_state.md` v4 counts each project's open items for the primer's Current line; `cicada_project` lists the top five. The Projects page's Backlog section (Open · Doing · Done · All) opens an item as the third column; ⌘K has a Backlog group. `backlog_import.py` and `scripts/import-backlog.sh` file G-row tables and `### G<n>` sections keeping ids and statuses — an id already filed is skipped, so a second run changes nothing. **Open.** (1) v2: Sleep's Stage 1 proposes an inbox item "Add to the backlog?" when a conversation says so and no agent filed it, graded by G113 like every resolution. (2) A note's model and effort: the wire carries `authorModel`/`authorEffort` (null in v1); round 4's per-turn join fills them. (3) Whether a backlog write should count as a mention of its project for decay — v1 says no. (4) **DECIDE (owner):** once this very backlog lives in the owner's bank, does `docs/goals/` in this public repository stay its public mirror — and which way would it sync — or become a pointer? (5) Editing a description, triage, links and order in the app (the PATCH already takes triage, `paid` and links). | 🛠️ v1 built on `feat/r4-backlog-in-memory` |
```

  G13's row: replace its closing `and the dogfood demo. | 🔲 |` with `and the dogfood demo. **2026-09-24:** **G150**
  makes a project's backlog memory — one file per item under `backlog/<project>/`, filed by agents
  (`cicada_add_backlog_item`, the quick capture this row asked for) and by the person on the Projects page, found by
  ⌘K — and its importer files this very file's rows (the dogfood demo, once the owner runs it). What stays G13's: the
  board across every project, and Sleep's capture of undated "we should…" items (G150's v2 idea). | 🔲 |`.

- [ ] **Step 2: CLAUDE.md.** Add, in the Storage Layer, right before `### Live state + handshake (G53 / G75)`:

```markdown
### Backlogs (G150)

A project's backlog is memory, not a table in some repository: **one markdown file per item** at
`<bank>/backlog/<project-id>/<item-id>.md`. Frontmatter: `id`, `title` (the brief task), `project`, `status`
(`open | doing | done | dropped`), `triage` (`apply | research | decide`, optional), `paid` (the 💸 flag), `created` /
`updated` (the machine zone's days), `added_by` (`user` | a harness label | `cicada`), `session`, `links: [{kind:
pr|commit|url|doc|entity, ref}]`, `order` (hand-set), and last a `notes: [{at, by, session}]` sidecar. Body:
`## Description` (the reasoning) then `## Notes`, append-only `### <day> · <who>` entries — a status move is itself a
signed note, and a note is edited only through git history; any heading inside a text is demoted so it can never forge
a note. **Never an entity page**: Stage 1 never extracts one, it never decays, and the writer never touches
`entities/`. Ids are `<PREFIX><n>` like G-ids — the project page's `backlog_prefix:`, else the prefix most of its items
share (an imported G-row list continues its sequence), else the name's initials (`Orchard` → `ORC`) — max+1, claimed by
an exclusive create (the backend and every stdio MCP process mint in one folder). **One writer**,
`api/services/backlog.py`, behind every door: REST (`routers/backlog.py` — `GET/POST /projects/{id}/backlog`,
`POST /projects/{id}/backlog/import`, `GET/PATCH /backlog/{project}/{item}`, `POST /backlog/{project}/{item}/notes`;
409 while Sleep runs; each write commits alone as `Backlog update <day>`, `Cicada-Author: user`, trigger
`user/companion_app`, an import as `Backlog import <day>`, `user/backlog_import`), MCP (`cicada_backlog` read;
`cicada_add_backlog_item` and `cicada_add_backlog_note` record — the harness as author and the conversation as
`Cicada-Session:`, refused while Sleep runs and in a demo bank; a remote connection without `sources` is told the
person's own words exist, never shown them), the importer (`backlog_import.py`, `scripts/import-backlog.sh`: G-row
tables and `### G<n>` sections, ids and statuses kept, an id already filed skipped) and the demo. Every text is
scrubbed (writer `backlog`), and an open item whose title matches a new one exactly refuses the new one — one row per
idea, later findings are notes. Both reads ETag over the `backlog` sync component (a stat walk) and `entities`; neither
is a Store domain (`BacklogCache` in the app, like `ProjectsCache`). A note's model and effort are joined to its turn at
read once round 4's per-turn join lands; until then a note names its harness.
```

  Six touch-ups:
  - The live-state paragraph's "A digest of the `entities`/`inbox`/`episodes`/`bank` sync components is stored as
    `inputs_version`" (`:430`) → "`entities`/`inbox`/`episodes`/`bank`/`backlog`" (R-B16 adds the component).
  - The `_state.md` schema paragraph ("**`_state.md` schema v3 (G141):** …") gains, at its end: "**v4 (G150)** adds
    `backlog_open` (items open or doing) to a project row that has any, and `backlog` joins the input components; the
    primer's Current row says "backlog: n open" under the same gate as `now`/`next`. Contract item 3 names the backlog
    tools (CONTRACT_VERSION 7)."
  - The **Triggers** list gains `user/backlog_import` (G150's importer) after `user/companion_app …`, and its
    `user/companion_app` parenthesis gains "and the Backlog section's, `Backlog update <date>`".
  - The MCP section's **Recall (G140)** paragraph (it ends "…The primer does not name `cicada_add_source` until S3's
    contract.") gains, at its end: "**`cicada_backlog`**, **`cicada_add_backlog_item`** and
    **`cicada_add_backlog_note`** (G150) read and file a project's backlog — see Backlogs."
  - The Projects page paragraph gains a bullet after **The story**: "- **Backlog (G150):** after Plan, text tabs Open ·
    Doing · Done · All (a dropped item only under All); rows with the id, the title, a triage tag and the age of the
    last note; Add to backlog. A row opens the item as the third column — the title as the heading, the moves, the
    description and every note as page prose signed with its author's mark, the links, Add a note. The third column is
    one slot: the Reader, else a backlog item, else an entity's card." — and "Esc closes the Reader, then the card, then
    the project" becomes "Esc closes the Reader, then the item or card, then the project".
  - "31 routers mounted" → "32 routers mounted"; the SQLite FTS5 paragraph's "media/paper metadata and inbox
    questions, in six per-kind FTS5 tables" → "media/paper metadata, inbox questions and backlog items (G150), in seven
    per-kind FTS5 tables"; the Find palette paragraph's "appends conversations, beliefs (superseded ones as history)
    and whatever the local tier missed" → "appends conversations, beliefs (superseded ones as history), backlog items
    (G150; the server tier only) and whatever the local tier missed". Both old phrases wrap across a line break in
    CLAUDE.md (`:472-473` and `:915-916`), so match them line by line, not as one string.

- [ ] **Step 3: TODO.md.** Under `## Where things stand (end of 2026-09-24) — round 3`, before its first paragraph,
  add:

```markdown
**Round 4 — G150, backlogs live in memory** (2026-09-24, `feat/r4-backlog-in-memory`, plan
`2026-09-24-r4-backlog-in-memory.md`). A project's backlog is one markdown file per item in the bank, filed by agents
over MCP (`cicada_add_backlog_item`, `cicada_add_backlog_note`, `cicada_backlog`) and by the person on the Projects
page, found by ⌘K, every note signed; the primer tells an agent what to do when the person says "put it in the
backlog". `scripts/import-backlog.sh` files this repository's G-row backlog into a project's backlog, idempotently —
**importing the owner's real backlog into his bank waits for his OK** (the orchestrator runs it after merge). 27
rulings (R-B1…R-B27), five dated in DESIGN_RULES §9. Merge notes: `CONTRACT_VERSION` 7 / remote 5, `_state.md` v4 and
the FTS `SCHEMA_VERSION` "4" take the next number past any other round-4 bump; a note's `authorModel`/`authorEffort`
are filled by round 4's per-turn join once it is on `dev`.
```

  and add to **Open owner questions**: "(4) G150: once the Cicada backlog lives in the bank, does `docs/goals/` stay
  its public mirror (and which way does it sync), or become a pointer?"

- [ ] **Step 4: DESIGN_RULES §9.** Append to §9's dated list (after the PJ-5 lines, before the paragraph that starts
  "This file landed on its own"):

```markdown
- **2026-09-24: G150 ships without the `cicada.design.focus` flag (R-B23, DR-73).** R-DS1's reasons hold unchanged; comparison is the installed build against the branch on a freshly generated demo bank.
- **2026-09-24: A project's Backlog section reads Open · Doing · Done · All, and a dropped item shows only under All (R-B19, DR-45).** The "resting projects only under All" precedent (R-PP6). Folded, the section says "n open" beside its label; open, the tabs carry the counts — the brief's "count in the eyebrow" without saying it twice (DR-38).
- **2026-09-24: A backlog item's id is on its row, as a G-id is (R-B24, a DR-54 departure).** DR-54 keeps machine ids in `.help`; a backlog id is the address the person and agents cite ("cite `G74a` the way you would cite a ticket"), so it is shown — in `metaFont`, `textTertiary`, tabular, never monospace (DR-19). The file path stays in `.help`.
- **2026-09-24: A backlog item's description and notes render as page prose, not in the quote face (R-B20, DR-18).** DR-18's door is for words someone said in a conversation; a note is a written document that may hold lists and code, so it goes through `MarkdownBody`. Each note still says who wrote it, with their real mark (DR-52).
- **2026-09-24: The Projects page's third column is one slot — the Reader, else a backlog item, else an entity's card (R-B21, DR-28, DR-31).** Opening one replaces the other; opening an item closes a Reader the old selection opened (DR-29); Esc closes the Reader, then the item or card, then the project.
```

- [ ] **Step 5: Check the privacy rule, then commit.** `cd <worktree> && git diff -- docs CLAUDE.md | rg -n -i
  "/users/|/private/|@|https?://"` prints nothing new but the repository's own public references; the added text names
  no real person, employer, project or conversation — its examples are `Orchard`, `alpha-project`, `rover-arm-project`,
  `bob-example`.

```bash
cd <worktree> && git add docs/goals/memory-evolution.md docs/goals/TODO.md CLAUDE.md docs/design/DESIGN_RULES.md \
  && git commit -m "docs: G150 backlogs live in memory — the row, CLAUDE.md, the handoff, §9 (G150 R-B19…R-B27)

G150 records the owner's request, the design as built (one file per item, one
writer, MCP and app doors, the importer) and what stays open: Sleep proposing an
item (v2), the per-turn model join, decay, the public-mirror question. G13
points at it; CLAUDE.md gains the Backlogs paragraph; DESIGN_RULES §9 dates five
rulings.

<attribution lines>"
```

---

## Not in scope

- **Importing the owner's real backlog into his bank.** The orchestrator runs `scripts/import-backlog.sh` (or the
  REST route) after merge, with his OK. No task here reads or writes a real bank.
- **Syncing the bank back to `docs/goals/`**, or retiring `docs/goals/` to a pointer — the owner's question (G150
  open 4).
- **Sleep extraction** of backlog items (G150's v2: an inbox "Add to the backlog?" graded by G113). v1 extracts
  nothing; no LLM runs anywhere in this track.
- **The per-turn model/effort join** for notes (round 4's C3 track owns the join; R-B6's seam is where it is called).
- **An application-wide board** across every project (G13 keeps it), a backlog on the owner's own page, and
  counting a backlog write as a project mention for decay (G150 open 3).
- **Editing in the app** a description, triage, `paid`, links or `order`; **deleting** an item (dropped is the end
  state, and git is the history); moving an item between projects; sub-items.
- **Keyboard shortcuts** for the Backlog section (L · M · D stay the Projects page's; the section's add field stands
  them aside while typing).
- **The Home page, the entity card or the Graph** showing backlog items; notifications about them.
- **Any contract shape** (C1–C7) — none is changed.

## Reported to the orchestrator

1. **The note model/effort seam (R-B6).** `routers/backlog._note` builds every note on the wire; once the C3 track's
   join helper is on `dev`, call it there with `(note.session, note.at)` to fill `author_model`/`author_effort`, and
   bump `backlog.BACKLOG_SHAPE` (the ETag must move when the body does). `at` is stored in C2's `recorded_ts` shape
   (UTC to the second, `Z`). The app already renders "Claude Code · Opus 5.5 · high effort" when the two arrive
   (`BacklogModel.authorLine`, tested). If that track ships a shared model-name formatter, `BacklogModel.modelWords`
   should call it.
2. **Version numbers that other round-4 tracks may also bump:** `handshake.CONTRACT_VERSION` 6 → 7 and
   `REMOTE_CONTRACT_VERSION` 4 → 5 (and `test_handshake.py`'s pin), `state_dictionary.SCHEMA_VERSION` 3 → 4 (and
   `test_state_v3.py`), `search_index.SCHEMA_VERSION` "3" → "4". At merge, take the next integer past whatever `dev`
   holds.
3. **The demo gains a step** (`_write_scenario_backlog`, before the events). `projects-demo.json` is unchanged by it
   (verified in Task 2). If another track regenerates `projects-demo.json` (D6 caps participants), regenerate after
   merge as usual; `backlog-demo.json` is new and pinned by `test_backlog_app_fixture.py`.
4. **Row placement.** G150 is appended after G141; G142–G149 land from other branches — order the rows at merge.
   TODO.md's "where things stand" gains a round-4 paragraph other tracks will also touch.
5. **The import on a live bank.** `scripts/import-backlog.sh` writes a named bank in-process; for the owner's bank, run
   it when Sleep is not consolidating, or use `POST /projects/{id}/backlog/import` on the running backend (409 while
   Sleep runs). This repo's backlog is `docs/goals/memory-evolution.md` with the default prefix `G` (R-B15 keeps
   `R`/other tables out); a project page must exist first (the importer never creates one).

## Verification the orchestrator runs at the end

1. **The suites.**
   - `cd <worktree> && api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider` → 0 failures (3775 passed,
     1 skipped on the base, plus this track's). Re-run
     `test_agent_provenance.py::test_a_decay_only_change_lands_in_its_own_cicada_authored_commit` alone if it is the
     only red.
   - `cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5` builds; `swift test 2>&1 | tail -20` → 0 failures
     (2003 on the base, plus this track's). Re-run a `SleepViewModelTests` poll or search-latency failure alone before
     calling it.
   - `cd <worktree> && node --test app/CicadaApp/Tests/graph/*.test.js` → 8/8.
   - `api/tests/test_projects_app_fixture.py` passes with `projects-demo.json` untouched (`git diff dev --stat --
     app/CicadaApp/Tests/fixtures/projects-demo.json` is empty).
2. **An MCP round trip on a synthetic bank** (never the owner's): build one with `_synthetic_bank._bank(tmp)` (or a
   fresh demo with `demo_guard.is_demo` lifted), then through `mcp/server.py`'s `handle_tool` with `get_memory_path`
   pointed at it: `cicada_add_backlog_item {project: alpha-project, title, description}` → "Added AP1 …";
   `cicada_add_backlog_note {item: AP1, note, status: doing}` → "Noted on AP1 … — now doing."; `cicada_backlog
   {project: alpha-project}` lists it, and `{…, item: AP1}` shows the note signed by the harness. `git log -2` shows two
   `Agent write` commits, each touching only `backlog/alpha-project/AP1.md`, with `Cicada-Author` and
   `Cicada-Session`. The primer (`cicada_handshake`) names the three tools and says "never a second item".
3. **The import script on a synthetic G-row file, twice:** write a file shaped like `test_backlog_import.py`'s
   `SYNTHETIC` into a scratch directory; `scripts/import-backlog.sh <synthetic-bank> alpha-project <file>` prints
   `{"created": 7, …}` and makes one `Backlog import` commit; the second run prints `{"created": 0, "skipped": 7, …}`
   and `git rev-parse HEAD` does not move.
4. **The app, on a freshly generated demo bank** (installed build; 1440 × 900 and 1200 × 800; both themes; 1.0× and
   1.4×; the rail and the labelled sidebar). Screenshots go in the PR body (DR-71, DR-73).
   - Rover Arm Project → the Backlog section after Plan: tabs Open 2 · Doing 1 · Done 1 · All 5; Open shows RAP3 and
     RAP4 with their triage tags and ages; All shows RAP2 dimmed with "Dropped". Folded, the header says "3 open".
   - RAP3 opens as the third column: "Swap the gripper camera…" as the heading, "Added by Claude Code · <day>",
     Open · Research tags, Start · Mark done · Drop · Edit title, the description, two notes — Claude Code's with its
     real mark, then yours — and Add a note. Hover a note's day for the full date; hover the heading for the id and
     the file.
   - Writes: Add to backlog (a title and a why) files RAP6 and opens it; Start moves RAP4 to Doing at once (the tab
     counts follow); Add a note appends "You · <today's word>"; Edit title renames; an exact duplicate title answers
     with the 409 sentence in a toast. Start a Consolidate: every backlog control is disabled with its reason.
   - Esc closes the item, then the project; opening an evidence chip while an item is open replaces it with the
     Reader; a Lately chip opens an entity's card in the same slot.
   - ⌘K "camera" shows a Backlog group with RAP3; ⏎ lands on Projects with Rover Arm Project and RAP3 open.
5. **The privacy grep:** `cd <worktree> && git diff dev -- . ':!app/CicadaApp/Tests/fixtures'
   ':!api/tests/test_backlog_app_fixture.py' ':!api/tests/test_projects_app_fixture.py' | rg -n -i "/users/|/private/"`
   prints nothing new; the docs name no real person, employer, project or conversation.
6. **The PR body** cites G150 (and G13), every DR id in the commits, the five §9 lines, R-B1…R-B27 and the Reported
   list above, and ends with the attribution lines.
