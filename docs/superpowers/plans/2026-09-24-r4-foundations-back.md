# Round 4 foundations — backend (Track R4-back) — Implementation Plan

> **For agentic workers:** execute task by task, in order. Each task is ONE reviewable commit:
> failing test → implement → green → commit. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Before the owner's clean first run, the backend makes four things true. (a) Every memory
write an agent makes can be traced to its harness, its model and its reasoning effort. (b) An agent
can be connected by pasting one prompt into it. (c) The events in Apple Calendar can flow in. (d) A
big project no longer beachballs the app. This is the BACKEND half of round 4's foundations,
exactly per the round-4 brief (Decisions D1–D7, Contracts C1–C6). The parallel track
`feat/r4-foundations-app` builds the app side of every contract.

**Architecture:** Every new rule is a pure function or a per-request cache with a table test.
Nothing new is stored except two things: the per-turn `model`/`effort` sidecar keys (C1) and a
claim's `recorded_ts` (C2). Everything else is joined at read, engine-free
(`api/services/turn_authorship.py`). The one new endpoint that writes (`POST
/sources/calendar-local/sync`) reuses the G20 stager, the scrub, the demo gate and the scoped
commit writer that folders and Wispr Flow already use. The one new read endpoint (`GET
/agents/setup`) is built from the same step builders `GET /agents/wiring` serves, so the two can
never disagree.

**Tech Stack:** Python 3.12 / FastAPI / Pydantic (`api/`), markdown + git bank, pytest. No Swift.

**Brief:** the round-4 brief (orchestrator scratchpad, not committed). Its decisions and contracts
bind. Every one this track depends on is restated below where a task uses it, so nothing here
needs the scratchpad. Backlog rows: **G49** (the model reservation this lifts), **G76**
(paste-prompt install), **G105** (the one permitted transcript read), **G118** (spans, the
sidecar, the Reader payloads), **G126** (channels), **G133** (the stager, local sources),
**G141** (project timelines), **G142** (new: Apple Calendar through EventKit). Standing rules
that apply here: the privacy rule for docs, ETag ship-together, "no LLM at capture time",
engine-free read paths, portability, and "no prices, no tokens" in the app.

**The owner's design note for this round ("for good design checkout mobbin")** is for the app
track. This track ships no UI. Its only person-facing words are the setup prompts, their titles
and notes, the `Apple Calendar` channel label and `install.md`. They follow the house voice:
plain, friendly, no jargon.

**`<worktree>`** below means the r4-back worktree the orchestrator named (`.worktrees/r4-back`
under the repo). This plan names no author-machine path.

---

## What the code actually does today (verified on `feat/r4-foundations-back` @ `ecb59c7`)

**Capture (C1's seam).**
- `api/services/transcript_extract.py:76-80`: `Turn(role, text, ts)` has no model and no effort.
  `_Builder.assistant_text` (`:164-166`) buffers `(text, ts)`. `boundary` (`:174-183`) keeps
  the last pending line's `ts`. `_add` (`:185-204`) appends the `Turn`.
- `:308-322` is the Claude Code agent branch. It reads `message.content` blocks only; `message.model`
  and the top-level `effort` are never read. `:360-362` is Codex: every line that is not a
  `response_item` (so `turn_context` too) is counted as `other_type` and skipped.
- `api/services/transcript_capture.py:146-158`: `_turn_sidecar` builds `episode_staging.Turn`s
  and calls `stamps_for`. `:161-168` `_place_turns` sets the sidecar as the last key. `:324-326`
  is the unchanged path (same hash → no write). `:328-343` is the update path; it does not look at
  the previous sidecar.
- `api/hooks/capture.py:138-144` is the POST body: harness, session_id, transcript_path, cwd,
  hook_event. The stdin `effort` is never forwarded. `api/routers/capture.py:151-160`
  `TranscriptCaptureRequest` has no `effort`. `:192-201` is the `capture_transcript` call.
- `api/services/episode_staging.py:64` is `TURN_STAMP_KEYS = ("offset", "ts", "speaker")`.
  `:78-83` is `Turn(text, speaker, ts)`. `:181-193` is `_stamps`: an entry only for a timed turn,
  head-stable at `MAX_TURN_STAMPS` (`:69`, 500).
- Two tests pin the key set exactly, and both break when the tuple grows:
  `api/tests/test_transcript_turn_stamps.py:64` (`tuple(e) == TURN_STAMP_KEYS`) and
  `api/tests/test_episode_staging.py:38` (`set(entry) == set(TURN_STAMP_KEYS)`).
- `api/services/evidence.py:399-429` `turn_stamps` reads `ts`/`speaker` only. It stays unchanged:
  the new reader lives beside it (R4B-7).

**Claims and the wire (C2–C4's seams).**
- `api/services/claims.py:123-199` is `Claim`. It has `recorded_at` (a day), a first-writer
  `session_id` and `session_ids`; there is no second-precision stamp. `to_dict` (`:215-234`)
  omits empty optional keys (R7). `from_dict` is at `:236-266`.
- `api/services/agentic_write.py:267-289` is the `write_claim` signature. `:465-485` builds the
  `Claim`. `_withdrawal_record` is at `:616-651` and `retract_claim` at `:654-716`.
- `api/services/progress.py`: `record_happening` `:421-425` (Claim `:480-487`), `set_milestone`
  `:507-510` (Claim `:537-545`), `advance` `:557-560` (`build` `:586-595`), `withdraw` `:667-668`
  (record `:700-701`).
- `api/services/watch_record.py:163-173` is `record`, and it calls `write_claim` at `:215-219`.
- `api/services/mcp_tools.py` is the one MCP seam. Stdio (`mcp/server.py:921-965`) and remote
  (`api/remote/runtime.py:181-199`) both call it. `write_claim` is at `:1120-1175`,
  `retract_claim` at `:1293-1322`, `note_progress`'s `common` dict at `:1033-1034` and
  `record_watch` at `:414-418`.
- `api/services/claim_reconciler.py:148-170` `_reinforce` moves `recorded_at` but never moves
  `session_id` or `authored_by` (the first writer's).
- `api/services/transclusion_resolver.py:45-86` `claim_to_model(claim)` is the ONE Claim →
  `ClaimModel` builder. It has no bank access. Its call sites are `routers/claims.py:49-53` (via
  `_claim_to_model`, used at `:99` and `:124`), `routers/projects.py:225`,
  `transclusion_resolver.py:202,225`, `project_timeline.py:721,737,745,807` and
  `api/tests/test_agent_labels.py:72,74`.
- `api/models/schemas.py:711-725` is `EvidenceModel`, `:739-786` is `ClaimModel`, `:841-861` is
  `EpisodeTurn`, `:878-905` is `EpisodeText` and `:926-936` is `ProvenanceContributor`.
- `api/services/provenance.py:100-159` `episode_document` builds turns as
  `EpisodeTurn(**asdict(t))` (`:157`). `:280-288` counts contributors from `authored_by`.
  `:458` builds a citation row's `EvidenceModel(**ev.to_dict())`. `provenance.py` must never
  import the capture writer (`test_episode_text_endpoint.py:213-226`).
- `api/services/git_service.py:302` is `AUTHOR_SHAPE = "harness-1"`. It is folded into the ETags
  of `/contributors` (`routers/contributors.py:34`), `/entities/{id}/provenance`
  (`routers/claims.py:150-152`) and `/episodes/{id}/citations` (`routers/episodes.py:140`). It is
  NOT folded into `/episodes/{id}/text` (`routers/episodes.py:108-111`) or into either
  `/projects` ETag (`routers/projects.py:83-84, 104-105`). The projects bodies already carry
  `authorKind` through `ClaimModel`, so that gap exists today.
- Codex exposes no session id to an MCP server (`mcp/server.py:69-116`: `CLAUDE_CODE_SESSION_ID` →
  `CICADA_SESSION_ID` → a `ses_*` fallback). A Codex MCP write therefore can never be joined to a
  captured turn. See "Known limits".

**Project timelines (D6's seam).**
- `api/services/project_timeline.py:52` is `PROJECT_SHAPE = "g141-2"`. `_participants`
  (`:572-588`) builds EVERY deduped participant of a moment, and `_moments` passes them all at
  `:637`. `_happening` (`:787-807`) builds a `TimelineParticipant` for EVERY `c.participants`
  entry, and at `:807` it embeds `claim_to_model(c)`, which carries every participant a second
  time as `ParticipantModel`s.
- `ProjectNow.last` is the same `TimelineItem`, so the list ships a third time.
- `_cluster` (`:1066-1075`) caps linked pages at `GROUP_CAP` (8), but appends EVERY name no page
  holds yet (`members[:GROUP_CAP] + hints[label]`, `:1074`). On a happening that cites 622
  unlinked papers, that is 622 more rows.
- `api/services/project_text.py:228-230` prints a `<url>` for every document participant. The
  MCP `cicada_project` line for such a happening is therefore 622 URLs long.
- `schemas.py:1083-1099` `TimelineItem` has `participants` and no total.
- `api/tests/test_projects_app_fixture.py` pins `app/CicadaApp/Tests/fixtures/projects-demo.json`
  to the demo wire byte for byte. It is regenerated with `CICADA_WRITE_APP_FIXTURE=1`, and this
  track owns it this round.

**Agent wiring (C5's seam).**
- `api/services/agent_wiring.py:31` is `PROBE_TIMEOUT_S = 2.0`. `_harness` (`:81-107`) builds
  the `mcp`/`hook` argv inline (`:93-100`). `probe` (`:127-135`) already gathers the two CLI probes
  concurrently (`asyncio.create_subprocess_exec`, `connections/base.py:174-216`). The 2 s budget
  is what failed live: `claude mcp get` starts the server to health-check it.
- `_gemini_cli` (`:110-124`) is read-only (R-IA15). The shared argv fixture is
  `api/tests/fixtures/agent_wiring_argv.json`, and the app's `AgentWiringCatalogTests` also reads
  it. This plan does not touch it.
- The app already builds Cursor's link and Claude desktop's snippet in
  `app/…/Views/Connect/ConnectView.swift:53-70`: base64 of the inner `{command, args, env}`
  object, percent-encoded, with `name=cicada`.

**Calendars (C6's seam).**
- `api/services/calendar_registry.py` covers ICS subscriptions only. Its episode body shape is
  `_episode_body` (`:330-345`): `# title`, `**Start:**`, `**End:**`, `**Location:**`,
  `**Calendar:**`, `## Description`. It dates the episode the day Cicada learned of it.
- `api/routers/local_sources.py:34` is `_DEMO_GATE`. `:132-206` `sync_folder` is the "app reads,
  backend parses" pattern: stage, `sync_state.record_sync`, then
  `folder_source.commit_paths_for(...)` (`folder_source.py:665-730`, scoped paths, a write-ahead
  ledger).
- `api/services/channel_registry.py:39-54` is `CHANNEL_IDS`. `_local_channel` is at `:221-252`,
  and `build_channels` (`:255`) appends local rows after the fixed list (`:337-345`, R-LS25). Two tests pin the exact
  fixed list: `api/tests/test_source_channels.py:259-262` and `:333-336`.
- `api/tests/test_folder_source.py:230-244` pins `APP_SYNC_ROUTED`, the set of channel ids the
  registry can emit with a `sync` action. Its Swift twin is
  `ChannelSyncRoutingTests.registrySyncIds`, and every id needs a handler in
  `ChannelActions.syncRoute` (app side), or the app's "Sync now" throws "Unknown channel".
- `api/services/episode_scrub.py:36-39` is `WRITERS`, the ledger's closed writer enum. It has
  `calendar` but no `calendar-local`, so an unlisted writer is recorded as `other`.
- `api/tests/test_transcript_turn_stamps.py:128-140` is a lint (R-CS7). It pins the exact set of
  modules under `api/`/`mcp/` whose source holds the literal `"turns"` (or `'turns'`) to
  `{episode_staging.py, evidence.py, transcript_capture.py}`. A new module that reads the sidecar
  key by name fails it.
- `api/services/source_overview.py:82-102` is `CATALOG`. The ICS row is at `:99`.
- `api/tests/test_demo_capture_routes.py:22-39` is `GATED`. Every new POST under `/sources/` must
  appear there.

**Install (G76's seam).**
- `README.md:118-121` has the clone and install steps. `install.sh` skips its key prompts when
  stdin is not a TTY (`:252`). `scripts/doctor.sh:70-80` still checks `_index.md` and
  `leann/*.meta.json`, and both fail on a brand-new bank. That is G76's open prerequisite, so
  `install.md` must not tell an agent to loop `make doctor`.

**Baseline on this base (2026-09-24):** the backend suite is `3775 passed, 1 skipped`.

---

## Global Constraints

- Work ONLY in `<worktree>` (branch `feat/r4-foundations-back`, based on `dev` @ `ecb59c7`).
  Every shell command is `cd <worktree> && <cmd>` with the ABSOLUTE path, because zoxide hijacks a
  relative `cd` (ignore its stderr warning). Never use a bare `grep --include=*.ext`: zsh globs
  it.
- NEVER read `<repo>/memory` (any bank), `~/.cicada`, `~/Library/Safari` or `~/.claude/projects`.
  Every fixture is synthetic (`alpha-project`, `bob-example`, `example.com`). Every transcript
  line in a test is written by the test with the real key names, and no real transcript is ever
  read.
- Python: `cd <worktree> && api/.venv/bin/python -m pytest <files> -q -p no:cacheprovider`. The
  full `api/tests` run must report 0 failures. One case is known to be order-dependent:
  `test_agent_provenance.py::test_a_decay_only_change_lands_in_its_own_cicada_authored_commit`
  passes alone. If it is the ONLY red, re-run it alone and report both results. Anything else red
  is this track's to fix.
- Never `git add -A`. Stage named files only. Never commit `memory/`, `logs/`,
  `.claude/settings.json`, `api/.venv` or `*-report.md`. Do not push, do not create branches or
  worktrees, do not dispatch subagents, and ignore Devin/PR comments.
- **No Swift.** The app side of every contract is `feat/r4-foundations-app`'s. The one app-path
  file this track writes is the regenerated `app/CicadaApp/Tests/fixtures/projects-demo.json`,
  which the orchestrator assigned here this round.
- **Contracts are fixed.** Never change a C1–C6 shape. Anything added beyond a contract must be
  additive and appear in "Flags for the app track" below.
- **Rails:** no LLM at capture time. Read paths are engine-free: bank files only, never
  `~/.claude`. ETag ship-together: a body that changes for the same files folds a shape into its
  ETag. Secrets live only in `~/.cicada/secrets.env`. Portability: no owner name and no
  author-machine path in code, tests, docs, commits or PR bodies. Telemetry records ids and enums
  only.
- Docstrings explain WHY and cite the G-row, decision (D1–D7), contract (C1–C6) or ruling (R4B-n)
  that motivated the rule. Match the density of the file you touch.
- Every commit message ends with the attribution lines your session's system reminder gives. Cite
  the G-rows and contract ids in the subject or body.
- Line numbers above are from `ecb59c7` and drift as tasks land. Re-read the cited code before
  each edit.

---

## Rulings (binding — each decides a choice the brief left open, with the reason)

- **R4B-1 (D6): the first 12 participants in the claim's own order, plus `participantsTotal`.**
  - Order is the sentence order `progress._participants` wrote, so the chips the app draws are
    the words the sentence links first.
  - `participantsTotal` is on EVERY `TimelineItem`: `0` for history and created rows, and the
    deduped count for a moment.
  - `now.last` is the same `TimelineItem` object, so the same code caps it.
  - On the timeline wire the embedded `claim` carries the same first 12. It is built from
    `dataclasses.replace(c, participants=c.participants[:12])`, never by mutating the claim,
    because `_CLAIMS_CACHE` shares `Claim` objects across requests. No other surface's claim is
    capped.
  - Cluster hints (names no page holds yet) are capped at `GROUP_CAP`, like linked pages. `more`
    still counts linked pages only (task-5 review r1's rule): a name is a hint, a page is a fact,
    so dropping the 9th hint loses nothing factual.
  - `cicada_project`'s line says `(+N more)` instead of printing N more URLs.
- **R4B-2 (C1): a model id is kept only if it looks like one; an effort only if it is one of the
  six.**
  - `agent_turns.clean_model` accepts `^[A-Za-z0-9][A-Za-z0-9._:/@+\-\[\]]{0,127}$`. This drops
    Claude Code's `<synthetic>`, its marker for a message no model produced.
  - `clean_effort` lower-cases and keeps only `minimal|low|medium|high|xhigh|max`.
  - Anything else is dropped, never guessed.
  - Only an agent turn carries either key. The value is taken from the LAST line of the kept final
    reply that names one, which is the same line whose `ts` the turn already takes.
- **R4B-3 (C1): the transcript wins, and the hook fills only what the transcript left empty.**
  - The Stop hook's `effort.level` fills the LAST body turn's `effort`, and only if (a) that turn
    is an agent's and (b) the transcript gave it none.
  - If the body's last turn is the person's (the reply has not been flushed yet), the hook's
    effort has no turn to land on and is dropped. It would otherwise label the previous reply.
  - On a re-capture, an agent entry keeps the `model`/`effort` the previous sidecar held at the
    SAME offset when the new read has none. The offsets are head-stable (R6), so a hook-supplied
    effort survives the next Stop.
  - An unchanged body is still not rewritten. G105's hash short-circuit stands, because a Stop
    only fires after a reply and so always brings new text.
- **R4B-4 (C1): an entry exists only for a timed turn (R-PB4, unchanged).**
  - A model never travels without a `ts`, and every Claude Code and Codex line carries one.
  - `TURN_STAMP_KEYS` becomes `("offset", "ts", "speaker", "model", "effort")`, with
    `TURN_STAMP_REQUIRED` being its first three.
  - An entry's keys keep that order.
- **R4B-5 (C2): only the MCP seam stamps `recorded_ts`.**
  - The stamp is `mcp_tools._now_ts()` → `episode_ids.utc_now_seconds()` (`YYYY-MM-DDTHH:MM:SSZ`).
    It is threaded as a keyword, like `today`, through `agentic_write.write_claim` /
    `retract_claim`, `progress.record_happening` / `set_milestone` / `advance` / `withdraw` and
    `watch_record.record`.
  - Stdio and remote share `mcp_tools`, so both are covered.
  - In-process writers pass none: Telegram, Wispr Flow, the Projects page, inbox answers and the
    demo generator. They have no captured turn to join, and the demo's wire stays byte-stable.
    The app fixture test would drift on a real clock.
  - `recorded_ts` pairs with the first-writer `session_id` and `authored_by`. A reinforce never
    moves it, just as it never moves those two.
  - It is omitted from the YAML when unset (R7's reason).
  - The claim wire also serves it as `recordedTs`. This is additive and beyond C3's list, so it
    is flagged.
- **R4B-6 (C3): the claim join, exactly.**
  - It applies to author kind `harness` with a `session_id` only. The chain is: that session's
    capture episode (`capture_kind: transcript` — an MCP episode of the same session is never it)
    → the last person's turn with `ts ≤ recorded_ts` → the next agent entry before the next
    person's entry → its `(model, effort)`.
  - Both sides are floored to the second. `recorded_ts` has second precision and a turn's `ts`
    has milliseconds, so a write stamped `10:05:00Z` belongs to the question asked at
    `10:05:00.600`.
  - A question with no kept reply answers nothing. So does a write past the head-stable cap
    (sidecar full and `recorded_ts ≥` its last `ts`).
  - With no `recorded_ts` (written before C2), the answer is the session's only model when there
    is exactly one, and effort follows the same rule independently.
  - Sleep claims keep `authorKind: model`: their model is their `Cicada-Author`, and they are
    never joined.
- **R4B-7 (C3): a span's model comes from the body's own turn start.**
  - Only an `assistant` span of an `ep_*` document is considered.
  - It is read only when that episode's sidecar names a model or effort, so other episodes cost
    nothing.
  - A stale span answers nothing.
  - The turn start comes from `evidence.turn_starts(body)`, and the sidecar entry must sit at
    exactly that offset with `speaker: assistant`. A line inside a person's message that only
    LOOKS like `assistant:` has no entry, so it gets no model.
  - Bodies are shared with the caller's per-request cache (the timeline's `episode_text` and
    provenance's `_Episodes.body`). That means one read per episode per request.
  - `evidence.py` is not touched: the tolerant reader of the two new keys is `agent_turns.stamps`.
- **R4B-8: `claim_to_model(claim, *, turns)`. The `turns` keyword is required, and `None` is
  allowed.**
  - A forgotten call site is a `TypeError` in the suite, not a silently null field.
  - `None` is only for a caller with no bank (a unit test).
- **R4B-9: `AUTHOR_SHAPE = "harness-2"`, and it is also folded into `/episodes/{id}/text` and
  both `/projects` ETags.**
  - Their bodies now carry turn models, and the projects bodies already carried `authorKind`.
    This closes the gap noted above.
  - No `VersionVector` mapping is owed, because none of these is a Store domain.
- **R4B-10 (C5): `GET /agents/setup` never probes.**
  - It builds the prompt from the same step builders `/agents/wiring` uses (`mcp_step`,
    `hook_step`).
  - It always includes both steps for Claude Code and Codex. The prompt tells the agent that "If
    one says Cicada is already set up, that's fine."
  - The binary is the absolute path when the backend resolves it, and the bare name otherwise.
  - Gemini's argv follows the Gemini CLI docs (`gemini mcp add [options] <name> <command>
    [args...]`, `-s user`, `-e KEY=value`; checked 2026-09-24, not run). It is served ONLY as a
    prompt. `/agents/wiring`'s gemini row stays read-only (R-IA15): the APP never runs an
    unverified CLI, but the person's own agent running it in the person's session is the
    person's act.
  - Cursor's link is base64 of the inner `{command, args, env}` object, percent-encoded. These
    are the same bytes `ConnectView.swift:66-70` builds.
  - The Claude desktop config `path` is the literal `~`-relative string; the app expands it and
    merges.
  - `kind: "remote"` is reserved: no harness in this round's list produces it.
- **R4B-11 (C5): the prompt stays ≤ 1,200 characters, and its commands are never shortened.**
  - The prose is ≈ 420 characters (421 for Claude Code, measured). That leaves room for
    commands up to about a 60-character checkout path.
  - Measured with the plan's code: a 41-character checkout gives 1,033 characters for Claude
    Code, 1,003 for Codex and 581 for Gemini CLI. A 54-character checkout gives 1,120 for Claude
    Code.
  - The test asserts the cap for a 41-character checkout path. A longer path can exceed it:
    shortening a command would break "names every command verbatim".
- **R4B-12: probe budget 6 s (was 2 s). The probes still run side by side.**
  - A test now pins the concurrency.
  - "A timeout is `unknown`, never `off`" is unchanged.
- **R4B-13 (C6): the calendar route.**
  - The route lives in `routers/local_sources.py`, the "app reads, backend parses" router, behind
    `_DEMO_GATE`.
  - One request carries the WHOLE window, because tombstones need the complete set. More than
    `MAX_EVENTS` (5,000) events → 413. A `window.from`/`to` that is not an aware time, or is
    out of order → 422.
  - Tombstoning:
    - An existing `calendar-local:` episode is tombstoned only if (a) its calendar is named in
      this request's `calendars`, (b) its stored `event_start` is in `[from, to)`, and (c) it was
      not posted. A calendar the request does not name says nothing about its events.
    - A tombstoned event that comes back clears its stamp (R-F1).
  - Body limits:
    - Notes are scrubbed FIRST, then cut at 2,000 characters. A passcode that straddles the cut
      is redacted whole.
    - A link keeps scheme, host and path only. Userinfo, query and fragment are dropped, because
      a meeting passcode lives in the query (`?pwd=`).
    - Attendees: the first 50, then `(+N more)`.
    - Title, location, organizer and calendar name: 300 characters each.
    - The title is scrubbed too, because it lands in frontmatter the stager does not scrub.
  - Dating: the episode is dated the day Cicada learned of the event (the ICS path's rule). The
    event's own times go in the body and in `event_start`/`event_end`, with `calendar_id` beside
    them.
  - Staging: `source_id = calendar-local:<id>`, `origin = source = calendar-local`.
  - Scrub ledger: the drafts' `writer` and the module's own `episode_scrub.record` both use
    `calendar`. It is already in `episode_scrub.WRITERS`, and the ICS path uses the same word. A
    `calendar-local` writer would be recorded as `other`.
  - Commit: only the stager's paths, author `user`, trigger `capture/calendar`, channel
    `calendar-local`. `sync_state.json` is left to the next sweep, as folders and Wispr Flow do.
  - No Sleep gate. It stages episodes only, like a folder sync.
  - The channel is ALWAYS listed so Settings → Integrations and the Welcome can offer it before
    the first sync. It is appended after the fixed ids (R-LS25) in `_local_channel`'s shape:
    label `Apple Calendar`, noun `event`, actions `["sync", "manage"]`.
  - Because the row carries `sync`, `calendar-local` joins `APP_SYNC_ROUTED`
    (`test_folder_source.py`). The app's `ChannelActions.syncRoute` and
    `ChannelSyncRoutingTests.registrySyncIds` must gain it too. That is flagged for the app track
    (Flag 4).
  - The Sources `CATALOG` gains its row, so its episodes never render as a raw id (Sources v2's
    A2).
- **R4B-14 (G76): `install.md` is for a person, and the agent follows it.**
  - The flow is: clone to `~/cicada` (a folder that stays put), `./install.sh`,
    `make install-app`, `open ~/Applications/Cicada.app`, then `curl …/healthz`.
  - It never loops `make doctor`: two of its checks fail on a brand-new bank until the first
    Sleep (G76's open prerequisite).
  - The agent asks before installing any missing tool, and never types or prints a key.
  - `~/cicada` may already exist without being a checkout. An older install whose checkout lives
    elsewhere made `~/cicada/memory` there (install.sh's default memory path). In that case
    `git clone` refuses a non-empty folder, and `git pull` has no repo. So the agent pulls only
    when `~/cicada/install.sh` exists, and otherwise stops and asks.
- **R4B-15 (C4): `/episodes/{id}/text`'s `agent` is the most recent agent turn's, or null.**
  - It is read from the WHOLE document's turns, before the Reader's 400,000-character cut.
  - The value is that turn's sidecar entry at exactly its start. If that entry names neither a
    model nor an effort, `agent` is null. This happens for a turn past the head-stable cap, or
    for a reply the harness did not label.
  - An older turn's model never stands in for the latest (D1: never guessed). The per-turn
    `model`/`effort` on `turns[]` still show each earlier turn's own value.
- **R4B-16 (C2): only the MCP seam stamps `recorded_ts`, which is narrower than C2's wording.**
  - C2 names "MCP / remote / agentic_write" writes. `agentic_write.write_claim` is also called
    in-process, by `telegram_capture.py:320`, `wispr_flow.py:434` and `demo_bank.py`. R4B-5
    stamps only what arrives through `mcp_tools`.
  - The field's shape is unchanged: it is optional, and legacy claims have none. Only the set of
    claims that carry it is narrower.
  - A claim with no captured turn to join gains nothing from a stamp, and the demo wire would
    drift on a real clock. This is flagged for the app track (Flag 1).

---

## File map

| File | Task | Responsibility |
|---|---|---|
| `api/models/schemas.py` | 1, 4, 5, 6 | `TimelineItem.participants_total` · `EvidenceModel.model/effort`, `ClaimModel.recorded_ts/author_model/author_effort`, `EpisodeTurn.model/effort`, `EpisodeAgent`, `EpisodeText.agent`, `ProvenanceModel`, `ProvenanceContributor.models` · `AgentSetupConfig`, `AgentSetupResponse` · `CalendarLocal*` |
| `api/services/project_timeline.py` | 1, 4 | `PARTICIPANTS_SHOWN`, the cap in `_moments`/`_happening`, hints cap in `_cluster`, `PROJECT_SHAPE = "g141-3"` · `_Bank.turns`, `turns=` at the four `claim_to_model` sites |
| `api/services/project_text.py` | 1 | `(+N more)` on a capped happening line |
| `app/CicadaApp/Tests/fixtures/projects-demo.json` | 1, 4 | regenerated (owned by this track this round) |
| `api/services/agent_turns.py` (new) | 2 | `EFFORTS`, `clean_model`, `clean_effort`, `Stamp`, `stamps(fm)` — the leaf vocabulary |
| `api/services/transcript_extract.py` | 2 | `Turn.model/effort`; Claude `message.model` + top-level `effort`; Codex `turn_context` |
| `api/services/episode_staging.py` | 2 | `TURN_STAMP_KEYS` grows, `TURN_STAMP_REQUIRED`, `Turn.model/effort`, `_stamps` writes them on agent turns |
| `api/services/transcript_capture.py` | 2 | `effort=` param, `_agent_fields` (carry-forward + hook fill), `_last_offset` |
| `api/hooks/capture.py` | 2 | forwards stdin `effort.level` as `effort` |
| `api/routers/capture.py` | 2 | `TranscriptCaptureRequest.effort` |
| `api/services/claims.py` | 3 | `Claim.recorded_ts` (omitted when unset) |
| `api/services/episode_ids.py` | 3 | `utc_now_seconds()` |
| `api/services/agentic_write.py`, `progress.py`, `watch_record.py` | 3 | `recorded_ts=` keyword threaded to every Claim they build |
| `api/services/mcp_tools.py` | 3 | `_now_ts()`; the four write tools pass it |
| `api/services/turn_authorship.py` (new) | 3, 4 | `turn_at`, `only_pair`, `TurnAuthorship` (per-request join) · `evidence_model` |
| `api/services/transclusion_resolver.py` | 4 | `claim_to_model(claim, *, turns)`; the transclusion sites |
| `api/routers/claims.py`, `routers/projects.py` | 4 | one `TurnAuthorship` per request; projects ETags fold `AUTHOR_SHAPE` |
| `api/services/provenance.py` | 4 | per-turn model/effort + `agent` on `/text`; contributor `models`; citation spans |
| `api/routers/episodes.py` | 4 | `/text` ETag folds `AUTHOR_SHAPE` |
| `api/services/git_service.py` | 4 | `AUTHOR_SHAPE = "harness-2"` |
| `api/services/agent_wiring.py` | 5 | `PROBE_TIMEOUT_S = 6.0`; `mcp_step`, `hook_step`, `gemini_mcp_step`, `server_spec`, `cursor_deeplink`, `setup_prompt`, `setup` |
| `api/routers/agents.py` | 5 | `GET /agents/setup` |
| `install.md` (new, repo root) | 5 | the paste-into-your-agent install for a fresh Mac (G76) |
| `api/services/calendar_local.py` (new) | 6 | `sync`, `body_for`, the caps, the tombstone rule |
| `api/routers/local_sources.py` | 6 | `POST /sources/calendar-local/sync` |
| `api/services/channel_registry.py`, `source_overview.py` | 6 | the `calendar-local` row; the catalog row |
| Tests (new) | 1–6 | `test_timeline_participants_cap.py`, `test_capture_model_effort.py`, `test_recorded_ts.py`, `test_turn_authorship.py`, `test_turn_authorship_wire.py`, `test_agent_setup.py`, `test_install_md.py`, `test_calendar_local.py` |
| Tests (edited) | 2, 3, 4, 5, 6 | `test_transcript_turn_stamps.py:64` and its R-CS7 lint (`:140`, the `"turns"` module set gains `agent_turns.py`), `test_episode_staging.py:38`, `test_watch_record.py` (+1 test), `test_agent_labels.py:72,74`, `test_agent_wiring.py` (+1 test), `test_demo_capture_routes.py` (`GATED`), `test_source_channels.py:259-262,333-336`, `test_folder_source.py:230-233` (`APP_SYNC_ROUTED` gains `calendar-local`) |
| Docs | 7 | `CLAUDE.md`, `docs/goals/TODO.md` (ruling 11), `docs/goals/memory-evolution.md` (G49, G76, new G142) |

---

### Task 1: D6 — big projects never beachball (participants capped, total always present)

**Files:**
- Modify: `api/models/schemas.py` (`TimelineItem`)
- Modify: `api/services/project_timeline.py` (`PROJECT_SHAPE`, new `PARTICIPANTS_SHOWN`, `_moments`, `_happening`, `_cluster`, the `dataclasses` import)
- Modify: `api/services/project_text.py` (`_happening_line`)
- Regenerate: `app/CicadaApp/Tests/fixtures/projects-demo.json`
- Test: `api/tests/test_timeline_participants_cap.py` (new)

**Interfaces:**
- Produces: `TimelineItem.participants_total: int` (wire `participantsTotal`, always present),
  `project_timeline.PARTICIPANTS_SHOWN = 12` and `PROJECT_SHAPE = "g141-3"`.
- Consumes: `project_timeline.build`, `project_text._happening_line`, `_demo_scenario.day_one`.

- [ ] **Step 1: Failing tests.** Create `api/tests/test_timeline_participants_cap.py`:

```python
"""Round 4 D6 — a big project never beachballs. One happening that cites 600
documents used to ship every participant three times (the item, its embedded
claim, and `now.last`) plus 600 "not a page yet" cluster rows, and the app drew a
chip for each. The wire now carries the first 12 in the sentence's own order and
an honest `participantsTotal`; the body grows with the cap, not the count.
Synthetic: the G141 demo scenario, every URL on example.com."""
from __future__ import annotations

from pathlib import Path

from _demo_scenario import T, d, day_one
from api.services import bank_index, markdown_parser, project_text, project_timeline
from api.services.claims import HAPPENED, Claim, parse_claims, write_claims

PROJECT = "rover-arm-project"
CLAIM_ID = "clm_rover_read_papers"


def _papers(n: int) -> list[dict]:
    return [{"role": "document", "surface": f"Paper {i:03d}", "url": f"https://example.com/papers/{i:03d}"}
            for i in range(n)]


def _add_happening(bank: Path, n: int) -> None:
    page = bank / "entities" / f"{PROJECT}.md"
    parsed = markdown_parser.parse(page)
    claims = [c for c in parse_claims(parsed.body) if c.id != CLAIM_ID]
    claims.append(Claim(
        id=CLAIM_ID, text="Read the cited papers for the arm controller", subject=PROJECT, predicate=HAPPENED,
        object="read the cited papers for the arm controller", object_kind="literal", observer="agent",
        status="done", valid_from=d(-1), valid_to=d(-1), recorded_at=d(-1), participants=_papers(n),
        date_basis="stated", authored_by="claude-code", origin="mcp"))
    markdown_parser.write(page, parsed.frontmatter, write_claims(parsed.body, claims))
    bank_index.invalidate()


def _bank(root: Path, n: int) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    bank = day_one(root, index=False)
    _add_happening(bank, n)
    return bank


def _build(bank: Path):
    return project_timeline.build(bank, PROJECT, tz_name="UTC")


def _item(timeline):
    return next(i for i in timeline.items if i.id == CLAIM_ID)


def test_an_item_carries_the_first_twelve_in_order_and_the_honest_total(tmp_path):
    timeline = _build(_bank(tmp_path, 600))
    item = _item(timeline)
    assert project_timeline.PARTICIPANTS_SHOWN == 12
    assert [p.surface for p in item.participants] == [f"Paper {i:03d}" for i in range(12)]
    assert item.participants_total == 600
    assert len(item.claim.participants) == 12          # the embedded claim is capped the same way
    assert timeline.now.last is not None and timeline.now.last.id == CLAIM_ID
    assert len(timeline.now.last.participants) == 12 and timeline.now.last.participants_total == 600
    wire = timeline.model_dump(by_alias=True)
    assert all("participantsTotal" in i for i in wire["items"]), "always present, 0 when there are none"


def test_the_body_grows_with_the_cap_not_the_count(tmp_path):
    small = len(_build(_bank(tmp_path / "a", 13)).model_dump_json(by_alias=True))
    big = len(_build(_bank(tmp_path / "b", 600)).model_dump_json(by_alias=True))
    assert big - small < 1_000, (small, big)


def test_names_no_page_holds_are_capped_like_pages(tmp_path):
    docs = next(g for g in _build(_bank(tmp_path, 600)).cluster.groups if g.label == "Documents")
    assert len([m for m in docs.members if m.pending]) == project_timeline.GROUP_CAP


def test_the_agents_reading_says_how_many_more(tmp_path):
    bank = _bank(tmp_path, 600)
    timeline = _build(bank)
    line = project_text._happening_line(timeline, _item(timeline), memory_path=bank, today=T, raw=False, texts={})
    assert "(+588 more)" in line
    assert line.count("https://example.com/papers/") == 12
```

Run: `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_timeline_participants_cap.py -q -p no:cacheprovider`
→ 4 failed (`PARTICIPANTS_SHOWN` / `participants_total` do not exist; the body difference is
hundreds of KB). That is the red.

- [ ] **Step 2: Implement.**

`api/models/schemas.py`, in `TimelineItem`, directly after `participants: list[TimelineParticipant] = []`:

```python
    # Round 4 D6: `participants` is the first `PARTICIPANTS_SHOWN` in the claim's
    # own order; the whole count rides here, always present (0 for a history row),
    # so the app's "+N more" never guesses and a 622-paper happening stays small.
    participants_total: int = 0
```

`api/services/project_timeline.py`:
- `from dataclasses import dataclass` → `from dataclasses import dataclass, replace`
- Replace the `PROJECT_SHAPE` block:

```python
# Bumped when a payload gains a field a client must see (the graph.NODE_SHAPE rule); rides both ETags.
# g141-2 (T5): happenings, open threads and `milestone` chains join the payload.
# g141-3 (round 4 D6): an item carries at most PARTICIPANTS_SHOWN participants + `participantsTotal`,
# and a cluster group at most GROUP_CAP names no page holds yet.
PROJECT_SHAPE = "g141-3"
```

- After `GROUP_CAP = 8                 # §6.4` add:

```python
PARTICIPANTS_SHOWN = 12       # round 4 D6: a happening citing 622 papers beachballed the app (R4B-1)
```

- In `_moments`, replace `participants=_participants(bank, root, owner, group),` with a local
  computed just before `items.append(TimelineItem(`:

```python
        people = _participants(bank, root, owner, group)
```

  and in the constructor:

```python
            participants=people[:PARTICIPANTS_SHOWN], participants_total=len(people),
```

- In `_happening`, change the loop header `for p in c.participants:` to
  `for p in c.participants[:PARTICIPANTS_SHOWN]:`. Then, before the `return`, add:

```python
    # R4B-1: the embedded claim carries the same first 12 — built from a copy, never a
    # mutation (`_CLAIMS_CACHE` shares Claim objects across requests); the item's total
    # is the honest count.
    shown = replace(c, participants=c.participants[:PARTICIPANTS_SHOWN])
```

  Then in the returned `TimelineItem(...)`, add `participants_total=len(c.participants),` after
  `participants=participants,` and change `claim=claim_to_model(c)` to
  `claim=claim_to_model(shown)`.

- In `_cluster` (`:1074`), replace the WHOLE line
  `            groups.append(ClusterGroup(label=label, members=members[:GROUP_CAP] + hints[label],`
  with these three lines (same 12-space indent, inside `if members or hints[label]:`):

```python
            # R4B-1: hints are capped like pages — a name is a hint, a page is a fact, so the
            # ninth unlinked name adds nothing a person can open; `more` still counts pages only.
            groups.append(ClusterGroup(label=label, members=members[:GROUP_CAP] + hints[label][:GROUP_CAP],
```

  The next line, `more=max(0, len(members) - GROUP_CAP)))`, stays as it is.

`api/services/project_text.py`, in `_happening_line`, directly after the
`for p in item.participants:` URL loop:

```python
    # Round 4 D6: the wire carries the first 12 participants; say how many the
    # sentence also named instead of printing every document's URL.
    hidden = item.participants_total - len(item.participants)
    if hidden > 0:
        line += f" (+{hidden} more)"
```

- [ ] **Step 3: Green, then regenerate the app fixture (the wire changed on purpose).**

Run: `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_timeline_participants_cap.py -q -p no:cacheprovider` → 4 passed.

Run: `cd <worktree> && CICADA_WRITE_APP_FIXTURE=1 api/.venv/bin/python -m pytest api/tests/test_projects_app_fixture.py -q -p no:cacheprovider`,
then without the variable → 2 passed. Then `git diff --stat app/CicadaApp/Tests/fixtures/projects-demo.json`.
The diff must be only the added `"participantsTotal": N` keys, with no other change. If anything
else moved, stop and find out why before committing.

Run the neighbours: `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_projects_router.py api/tests/test_projects_writes.py api/tests/test_project_timeline_events.py api/tests/test_note_progress_tool.py api/tests/test_mcp_stdio_golden.py -q -p no:cacheprovider` → 0 failed.

- [ ] **Step 4: Commit.**

```bash
cd <worktree> && git add api/models/schemas.py api/services/project_timeline.py api/services/project_text.py \
  api/tests/test_timeline_participants_cap.py app/CicadaApp/Tests/fixtures/projects-demo.json && \
git commit -F - <<'MSG'
fix(projects): a big project never beachballs — 12 participants + participantsTotal (round 4 D6, G141)

A happening citing hundreds of papers shipped every participant three times
(the item, its embedded claim, now.last) plus one "not a page yet" row per
name. The timeline wire now carries the first 12 in the sentence's order and
an honest participantsTotal on every item; cluster hints cap at GROUP_CAP;
cicada_project says "(+N more)". PROJECT_SHAPE g141-3; the app's demo fixture
regenerated (additive key only). Rulings R4B-1.

<attribution lines from your session's system reminder>
MSG
```

---

### Task 2: C1 — capture keeps each agent turn's model and effort (and nothing else of the line)

**Files:**
- Create: `api/services/agent_turns.py`
- Modify: `api/services/transcript_extract.py`, `api/services/episode_staging.py`,
  `api/services/transcript_capture.py`, `api/hooks/capture.py`, `api/routers/capture.py`
- Modify (tests): `api/tests/test_transcript_turn_stamps.py:64` and `:140` (the R-CS7 lint),
  `api/tests/test_episode_staging.py:38`
- Test: `api/tests/test_capture_model_effort.py` (new)

**Interfaces:**
- Produces: `agent_turns.EFFORTS`, `clean_model(v) -> str | None`, `clean_effort(v) -> str | None`,
  `Stamp(offset, ts, speaker, model, effort)` and `stamps(frontmatter) -> list[Stamp]` (ascending,
  tolerant, model/effort only on `speaker == "assistant"`).
- Produces: `transcript_extract.Turn.model/effort`; `episode_staging.TURN_STAMP_KEYS` (5 keys) and
  `TURN_STAMP_REQUIRED` (3); `episode_staging.Turn.model/effort`;
  `capture_transcript(..., effort: str | None = None)`; the request field `effort`.
- The sidecar entry becomes `{offset, ts, speaker, model?, effort?}` (C1).

- [ ] **Step 1: Failing tests.** Create `api/tests/test_capture_model_effort.py`:

```python
"""Round 4 D1 / C1 (G49 lifted for harness writes): the capture path keeps each
agent turn's model id and reasoning effort — two keys, nothing else of the line —
in the episode's `turns` sidecar, outside `content_hash`. Synthetic transcripts
only: the real key names, placeholder content; no real transcript is read."""
from __future__ import annotations

import io
import json

import pytest

from api.hooks import capture as hook
from api.services import episode_staging, markdown_parser, transcript_capture as tc, transcript_extract as tx

SID = "66666666-7777-4888-8999-aaaaaaaaaaaa"
CSID = "77777777-8888-4999-8aaa-bbbbbbbbbbbb"
SENTINEL = "SENTINEL-never-read"


def _user(text, ts="2026-09-24T10:00:00.000Z"):
    return json.dumps({"type": "user", "uuid": "u", "timestamp": ts, "sessionId": SID,
                       "cwd": "/home/example/alpha-project", "message": {"role": "user", "content": text}})


def _asst(text, *, model=None, effort=None, ts="2026-09-24T10:00:05.000Z", blocks=None, **top):
    msg = {"role": "assistant", "content": blocks or [{"type": "text", "text": text}], "usage": {"note": SENTINEL}}
    if model is not None:
        msg["model"] = model
    line = {"type": "assistant", "uuid": "a", "timestamp": ts, "sessionId": SID,
            "cwd": "/home/example/alpha-project", "message": msg, **top}
    if effort is not None:
        line["effort"] = effort
    return json.dumps(line)


def _cx(typ, payload, ts="2026-09-24T10:00:00.000Z"):
    return json.dumps({"timestamp": ts, "type": typ, "payload": payload})


def _cx_msg(role, text, ts="2026-09-24T10:00:01.000Z"):
    kind = "input_text" if role == "user" else "output_text"
    return _cx("response_item", {"type": "message", "role": role, "content": [{"type": kind, "text": text}]}, ts)


# --- the extractor -------------------------------------------------------------


def test_a_claude_reply_carries_its_model_and_effort_and_a_person_never_does():
    person, reply = tx.extract_claude_code([
        _user("Which index does alpha-project use?"),
        _asst("sqlite-vec.", model="claude-opus-5-5", effort="XHIGH"),
    ]).turns
    assert (person.model, person.effort) == (None, None)
    assert (reply.model, reply.effort) == ("claude-opus-5-5", "xhigh")  # lower-cased (R4B-2)


def test_the_final_replys_line_decides_not_narration_before_a_tool():
    conv = tx.extract_claude_code([
        _user("Check alpha-project."),
        _asst("Let me look.", model="claude-haiku-5", effort="low"),
        _asst("", blocks=[{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}}],
              model="claude-haiku-5", effort="low"),
        json.dumps({"type": "user", "uuid": "r", "timestamp": "2026-09-24T10:00:06.000Z", "sessionId": SID,
                    "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1",
                                                             "content": "ok"}]}}),
        _asst("All good.", model="claude-opus-5-5", effort="high"),
    ])
    assert (conv.turns[-1].model, conv.turns[-1].effort) == ("claude-opus-5-5", "high")


def test_an_unknown_effort_and_a_synthetic_model_are_dropped_never_guessed():
    reply = tx.extract_claude_code([_user("Q"), _asst("A", model="<synthetic>", effort="turbo")]).turns[-1]
    assert (reply.model, reply.effort) == (None, None)


def test_nothing_else_of_an_agent_line_is_read():
    conv = tx.extract_claude_code([
        _user("Q"),
        _asst("", blocks=[{"type": "thinking", "thinking": SENTINEL}], model="claude-opus-5-5"),
        _asst("A", model="claude-opus-5-5", effort="high", reasoning={"text": SENTINEL}),
    ])
    assert SENTINEL not in repr(conv)


def test_codex_turn_context_names_the_model_for_the_turns_that_follow():
    conv = tx.extract_codex([
        _cx("session_meta", {"id": CSID, "cwd": "/home/example/alpha-project"}),
        _cx("turn_context", {"cwd": "/home/example/alpha-project", "model": "gpt-5.5-codex", "effort": "high",
                             "user_instructions": SENTINEL, "summary": "auto"}),
        _cx_msg("user", "Plan alpha-project"),
        _cx("response_item", {"type": "reasoning", "summary": [{"type": "summary_text", "text": SENTINEL}]}),
        _cx_msg("assistant", "Plan drafted."),
        _cx("turn_context", {"model": "gpt-5.5-codex-mini", "effort": "LOW"}),
        _cx_msg("user", "Shorter please"),
        _cx_msg("assistant", "Done."),
    ])
    assert [(t.role, t.model, t.effort) for t in conv.turns] == [
        ("user", None, None), ("assistant", "gpt-5.5-codex", "high"),
        ("user", None, None), ("assistant", "gpt-5.5-codex-mini", "low")]
    assert SENTINEL not in repr(conv)
    assert conv.summary["dropped_messages"]["other_type"] == 2  # turn_context still counts as before


# --- the writer ----------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fresh_episode_cache(monkeypatch):
    monkeypatch.setattr(tc, "_episode_cache", {})


@pytest.fixture
def transcript(tmp_path, monkeypatch):
    folder = tmp_path / "claude-projects" / "-home-example-alpha-project"
    folder.mkdir(parents=True)
    monkeypatch.setattr(tc, "harness_root", lambda h: folder.parent)
    return folder / f"{SID}.jsonl"


@pytest.fixture
def memory(tmp_path):
    m = tmp_path / "memory"
    (m / "episodes").mkdir(parents=True)
    return m


def _capture(memory, transcript, lines, *, effort=None):
    transcript.write_text("\n".join(lines) + "\n", encoding="utf-8")
    r = tc.capture_transcript(memory, harness="claude-code", session_id=SID, transcript_path=str(transcript),
                              cwd="/home/example/alpha-project", keep_assistant=True, effort=effort)
    assert r.status in ("created", "updated"), r
    parsed = markdown_parser.parse(memory / "episodes" / f"{r.episode_id}.md")
    return dict(parsed.frontmatter), parsed.body


def test_agent_entries_carry_them_in_contract_order_outside_the_hash(memory, transcript):
    fm, body = _capture(memory, transcript, [_user("Q1"), _asst("A1", model="claude-opus-5-5", effort="xhigh")])
    person, reply = fm["turns"]
    assert tuple(person) == episode_staging.TURN_STAMP_REQUIRED
    assert tuple(reply) == episode_staging.TURN_STAMP_KEYS
    assert (reply["model"], reply["effort"]) == ("claude-opus-5-5", "xhigh")
    assert fm["content_hash"] == episode_staging.content_hash(body)  # the body alone (C1)


def test_the_hooks_effort_fills_the_last_reply_only_when_the_transcript_is_silent(memory, transcript):
    fm, _ = _capture(memory, transcript, [_user("Q1"), _asst("A1", model="claude-opus-5-5")], effort="max")
    assert fm["turns"][-1]["effort"] == "max"


def test_the_transcripts_own_effort_wins(memory, transcript):
    fm, _ = _capture(memory, transcript, [_user("Q1"), _asst("A1", effort="high")], effort="low")
    assert fm["turns"][-1]["effort"] == "high"


def test_a_hook_effort_with_no_reply_in_the_body_lands_nowhere(memory, transcript):
    fm, _ = _capture(memory, transcript, [_user("Q1"), _asst("A1", model="claude-opus-5-5"),
                                          _user("Q2", ts="2026-09-24T10:01:00.000Z")], effort="max")
    assert all("effort" not in e for e in fm["turns"])


def test_a_later_stop_keeps_what_the_hook_said_about_an_earlier_reply(memory, transcript):
    _capture(memory, transcript, [_user("Q1"), _asst("A1", model="claude-opus-5-5")], effort="max")
    fm, _ = _capture(memory, transcript, [
        _user("Q1"), _asst("A1", model="claude-opus-5-5"),
        _user("Q2", ts="2026-09-24T10:02:00.000Z"),
        _asst("A2", model="claude-opus-5-5", ts="2026-09-24T10:02:05.000Z")])
    assert [e.get("effort") for e in fm["turns"]] == [None, "max", None, None]


# --- the hook and the route -------------------------------------------------------


def _hook_body(tmp_path, payload):
    token = tmp_path / "api_token"
    token.write_text("tok")
    calls = []

    def post(url, body, tok, timeout):
        calls.append(json.loads(body))
        return 200, '{"status":"updated"}'

    assert hook.main(["--harness", "claude-code"], stdin=io.StringIO(json.dumps(payload)), environ={}, post=post,
                     log_path=tmp_path / "capture.log", token_path=token) == 0
    return calls[0]


def test_the_hook_forwards_effort_level_and_nothing_else_new(tmp_path):
    base = {"session_id": SID, "transcript_path": f"/home/example/.claude/projects/x/{SID}.jsonl",
            "cwd": "/home/example/alpha-project", "hook_event_name": "Stop"}
    body = _hook_body(tmp_path, {**base, "effort": {"level": "xhigh"}, "model": {"id": SENTINEL}})
    assert body["effort"] == "xhigh" and SENTINEL not in json.dumps(body)
    assert "effort" not in _hook_body(tmp_path, base)


def test_the_route_passes_the_hooks_effort_through(memory, transcript, monkeypatch):
    from fastapi.testclient import TestClient

    from api import config, main

    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    try:
        transcript.write_text("\n".join([_user("Q1"), _asst("A1", model="claude-opus-5-5")]) + "\n",
                              encoding="utf-8")
        client = TestClient(main.app)
        req = {"harness": "claude-code", "session_id": SID, "transcript_path": str(transcript)}
        r = client.post("/capture/transcript", json={**req, "effort": "medium"})
        assert r.status_code == 200, r.text
        fm = markdown_parser.parse(memory / "episodes" / f"{r.json()['episodeId']}.md").frontmatter
        assert fm["turns"][-1]["effort"] == "medium"
        assert client.post("/capture/transcript", json={**req, "effort": "x" * 40}).status_code == 422
    finally:
        config.get_settings.cache_clear()
```

Edit the two key-set pins. `api/tests/test_transcript_turn_stamps.py:64` becomes:

```python
    assert all(tuple(e)[:3] == episode_staging.TURN_STAMP_REQUIRED and set(e) <= set(episode_staging.TURN_STAMP_KEYS)
               for e in fm["turns"])
```

`api/tests/test_episode_staging.py:38` becomes:

```python
        assert tuple(entry)[:3] == st.TURN_STAMP_REQUIRED and set(entry) <= set(st.TURN_STAMP_KEYS)
```

The R-CS7 lint, `test_the_turns_key_has_one_shape_owner_and_one_reader`
(`api/tests/test_transcript_turn_stamps.py:128-140`), fails the moment `agent_turns.py` exists,
because `stamps` reads `(frontmatter or {}).get("turns")`. Replace its last line (`:140`) with:

```python
    # Round 4 C1: `agent_turns.stamps` is the tolerant reader of the two agent
    # keys (model/effort). It reads a non-list as no stamps, so "nothing reads a
    # count" still holds; `evidence.turn_stamps` stays the reader of ts/speaker.
    assert found == {"episode_staging.py", "evidence.py", "transcript_capture.py", "agent_turns.py"}
```

No other new module in this plan may spell the key. `turn_authorship.py` and `provenance.py`
read the sidecar only through `agent_turns.stamps`.

Run: `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_capture_model_effort.py -q -p no:cacheprovider`
→ red. The module imports cleanly, and the tests fail at run time:
- `AttributeError` on `episode_staging.TURN_STAMP_REQUIRED` and on `Turn.model`;
- `TypeError` on `capture_transcript(..., effort=...)`;
- the hook and route tests fail their `effort` assertions.

- [ ] **Step 2: Implement.** Create `api/services/agent_turns.py`:

```python
"""Which model answered a turn, and how hard it thought — the two agent-turn
facts a capture may keep (round 4 D1, contract C1; G49's reservation lifted for
harness writes, TODO ruling 11).

A leaf on purpose, standard library only: the writers (`transcript_extract`,
`episode_staging`) and the readers (`turn_authorship`, `provenance`) share ONE
vocabulary, and the read paths must never import the transcript extractor
(`test_the_provenance_module_is_engine_free`). `evidence.turn_stamps` stays the
reader of `ts`/`speaker`; `stamps` here is the tolerant reader of the whole
entry, the two new keys included.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: The reasoning-effort words the harnesses write (Claude Code's top-level
#: `effort`, the Stop hook's `effort.level`, Codex's `turn_context.payload.effort`).
#: Anything else is dropped, never mapped (R4B-2).
EFFORTS = ("minimal", "low", "medium", "high", "xhigh", "max")
# A model id looks like one: `claude-opus-5-5`, `gpt-5.5-codex`, `openrouter/x/y`.
# The first character rules out Claude Code's `<synthetic>` marker for a
# message no model produced (R4B-2).
_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-\[\]]{0,127}$")


def clean_model(value) -> str | None:
    """The raw model id, or None when it does not look like one."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text if _MODEL_RE.match(text) else None


def clean_effort(value) -> str | None:
    """One of :data:`EFFORTS`, lower-cased, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    return text if text in EFFORTS else None


@dataclass(frozen=True)
class Stamp:
    """One `turns` sidecar entry (R-PB4 + C1), cleaned. `model`/`effort` are
    None on every entry that is not an agent's."""

    offset: int
    ts: str | None
    speaker: str | None
    model: str | None = None
    effort: str | None = None


def stamps(frontmatter: dict | None) -> list[Stamp]:
    """The sidecar, ascending by offset. Tolerant like `evidence.turn_stamps`: a
    pre-PJ-4 integer count reads as no stamps, and a malformed or duplicate
    entry is skipped, never raised — a hand-edited episode must never fail a read."""
    raw = (frontmatter or {}).get("turns")
    if not isinstance(raw, list):
        return []
    out: dict[int, Stamp] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        try:
            offset = int(entry.get("offset"))
        except (TypeError, ValueError):
            continue
        if offset < 0 or offset in out:
            continue
        speaker = str(entry.get("speaker") or "") or None
        agent = speaker == "assistant"
        ts = entry.get("ts")
        out[offset] = Stamp(offset=offset, ts=str(ts) if ts not in (None, "") else None, speaker=speaker,
                            model=clean_model(entry.get("model")) if agent else None,
                            effort=clean_effort(entry.get("effort")) if agent else None)
    return [out[k] for k in sorted(out)]
```

`api/services/transcript_extract.py`:
- Add the import after the `episode_scrub` import:
  `from api.services.agent_turns import clean_effort, clean_model  # round 4 C1: one vocabulary`
- Extend the module docstring's kept list with a bullet after (b):

```
* from (b)'s lines, exactly two more facts and nothing else of them (round 4
  D1, C1): the model id and the reasoning effort — Claude Code's
  `message.model` and top-level `effort`, Codex's `turn_context.payload.model`
  and `.effort` — cleaned by `agent_turns` (unknown values dropped) and
  carried on the agent turn only;
```

- `Turn` gains two fields after `ts`:

```python
    # Round 4 C1: set on an agent turn only — what the harness recorded for the
    # kept reply's line; never inferred (R4B-2).
    model: str | None = None
    effort: str | None = None
```

- `_Builder.__init__`: `self.pending: list[tuple[str, str | None, str | None, str | None]] = []`
- `assistant_text`:

```python
    def assistant_text(self, text: str, ts: str | None, model=None, effort=None) -> None:
        if text and text.strip():
            self.pending.append((text, ts, clean_model(model), clean_effort(effort)))
```

- `boundary`, replace the body after `if not self.pending: return`:

```python
        joined = "\n\n".join(p[0] for p in self.pending)
        ts = self.pending[-1][1]
        # R4B-2: the last line of the kept reply that names one — the line whose
        # `ts` the turn already takes; narration before a tool was dropped with it.
        model = next((p[2] for p in reversed(self.pending) if p[2]), None)
        effort = next((p[3] for p in reversed(self.pending) if p[3]), None)
        self.pending = []
        if not self.keep_assistant:
            self.count_msg("assistant_by_flag")
            return
        self._add("assistant", joined, ts, model=model, effort=effort)
```

- `_add` signature becomes `def _add(self, role: str, text: str, ts: str | None, *, model=None, effort=None) -> None:`
  and its append becomes `self.turns.append(Turn(role=role, text=cleaned, ts=ts, model=model, effort=effort))`.
- Claude Code agent branch (`else:` after `if typ == "user":`), after the `isApiErrorMessage`
  check:

```python
            # Round 4 D1 (C1): exactly two keys of an agent line — `message.model`
            # and the top-level `effort` (a `{level}` object is read the same way).
            # Thinking, usage and every other key stay unread (G105).
            model = msg.get("model")
            effort = obj.get("effort")
            if isinstance(effort, dict):
                effort = effort.get("level")
```

  and the text call becomes `b.assistant_text(str(bk.get("text") or ""), ts, model, effort)`.
- `extract_codex`: before the loop add `ctx_model = ctx_effort = None`. Before
  `if typ != "response_item":` add:

```python
        if typ == "turn_context":
            # Round 4 D1 (C1): the model and reasoning effort for the agent turns
            # that follow, until the next turn_context — these two payload keys
            # only; instructions, policies and summaries are never read. Counted
            # as before, so the ledger's counts do not move.
            ctx_model, ctx_effort = payload.get("model"), payload.get("effort")
            b.count_msg("other_type")
            continue
```

  and `b.assistant_text("\n".join(texts), ts)` becomes
  `b.assistant_text("\n".join(texts), ts, ctx_model, ctx_effort)`.

`api/services/episode_staging.py`:
- The import line becomes `from api.services import agent_turns, bank_index, episode_ids, episode_scrub, markdown_parser`.
- Replace the `TURN_STAMP_KEYS` line:

```python
#: Keys of one ``turns`` sidecar entry (R-PB4) — the coordination contract, exactly.
#: Round 4 C1 adds ``model``/``effort``: written on an agent turn only, only when the
#: harness recorded them, in this order; every entry carries the first three.
TURN_STAMP_KEYS = ("offset", "ts", "speaker", "model", "effort")
TURN_STAMP_REQUIRED = TURN_STAMP_KEYS[:3]
```

- `Turn` gains `model: str | None = None` and `effort: str | None = None` after `ts`.
- `_stamps`: replace its two lines `if ts and len(out) < MAX_TURN_STAMPS:` and
  `out.append({"offset": offset, "ts": ts, "speaker": str(turn.speaker)})` with:

```python
        if ts and len(out) < MAX_TURN_STAMPS:
            entry = {"offset": offset, "ts": ts, "speaker": str(turn.speaker)}
            if turn.speaker == "assistant":  # C1: only an agent turn names a model
                if model := agent_turns.clean_model(turn.model):
                    entry["model"] = model
                if effort := agent_turns.clean_effort(turn.effort):
                    entry["effort"] = effort
            out.append(entry)
```

  Update `_stamps`'s docstring to `[{offset, ts, speaker, model?, effort?}]`.

`api/services/transcript_capture.py`:
- The import becomes `from api.services import agent_turns, demo_guard, episode_ids, episode_staging, markdown_parser, session_stats, telemetry`.
- `_turn_sidecar`: `episode_staging.Turn(text=t.text, speaker=t.role, ts=t.ts, model=t.model, effort=t.effort)`.
- Add after `_place_turns`:

```python
def _last_offset(conv: Conversation, body: str) -> int | None:
    """Where the body's LAST turn starts — `_body` joins `"{role}: {text}"`
    chunks with `\\n`, so it is the body's length minus that chunk's."""
    if not conv.turns:
        return None
    last = conv.turns[-1]
    return len(body) - len(f"{last.role}: {last.text}")


def _agent_fields(sidecar: list[dict], previous, effort: str | None, last_offset: int | None) -> list[dict]:
    """Round 4 C1 (R4B-3): what the transcript did not say about an agent turn.

    1. An agent entry the new read left without a `model`/`effort` keeps what the
       previous sidecar held at the SAME offset — offsets are head-stable (R6), so
       a hook-supplied effort survives the next Stop.
    2. The Stop hook's `effort.level` fills the LAST body turn only, only when it
       is the agent's and the transcript gave it none: the transcript wins, and a
       reply not yet flushed leaves the hook's value with no turn to land on
       rather than labelling the previous reply.
    Keys stay in `TURN_STAMP_KEYS` order."""
    before: dict[int, dict] = {}
    if isinstance(previous, list):
        for e in previous:
            if isinstance(e, dict) and e.get("speaker") == "assistant":
                try:
                    before.setdefault(int(e.get("offset")), e)
                except (TypeError, ValueError):
                    continue
    for entry in sidecar:
        if entry.get("speaker") != "assistant":
            continue
        was = before.get(entry["offset"], {})
        if "model" not in entry and (model := agent_turns.clean_model(was.get("model"))):
            entry["model"] = model
        if "effort" not in entry and (kept := agent_turns.clean_effort(was.get("effort"))):
            entry["effort"] = kept
    hook = agent_turns.clean_effort(effort)
    if hook and sidecar and last_offset is not None:
        tail = sidecar[-1]
        if tail.get("offset") == last_offset and tail.get("speaker") == "assistant" and "effort" not in tail:
            tail["effort"] = hook
    return [{k: e[k] for k in episode_staging.TURN_STAMP_KEYS if k in e} for e in sidecar]
```

- `capture_transcript` gains the keyword `effort: str | None = None` (after `bank`). Add this to
  the docstring: "`effort`: the Stop hook's `effort.level` for the reply it fired after (round 4
  C1, R4B-3)."
- In the create branch, `_place_turns(fm, _turn_sidecar(conv, body))` becomes:

```python
            _place_turns(fm, _agent_fields(_turn_sidecar(conv, body), None, effort, _last_offset(conv, body)))
```

- In the update branch, right after `fm = dict(markdown_parser.parse(existing).frontmatter)`, add
  `previous = fm.get("turns")`. Then its `_place_turns(fm, _turn_sidecar(conv, body))` becomes:

```python
        _place_turns(fm, _agent_fields(_turn_sidecar(conv, body), previous, effort, _last_offset(conv, body)))
```

- Extend the module docstring's sidecar paragraph with this sentence: "Round 4 (C1): an agent
  turn's entry also carries `model`/`effort` when the transcript (or, for the last reply, the
  Stop hook) recorded them."

`api/hooks/capture.py`: replace the `body = json.dumps({...}).encode("utf-8")` statement with:

```python
        fields = {
            "harness": harness,
            "session_id": session_id,
            "transcript_path": str(transcript_path),
            "cwd": payload.get("cwd"),
            "hook_event": payload.get("hook_event_name"),
        }
        effort = payload.get("effort")
        level = effort.get("level") if isinstance(effort, dict) else None
        if isinstance(level, str) and level.strip():
            # Round 4 D1 (C1): the reasoning effort of the reply this Stop fired
            # after, so the last turn has it even when its transcript line does
            # not. Only this one field is added; the backend validates it.
            fields["effort"] = level.strip()[:32]
        body = json.dumps(fields).encode("utf-8")
```

  Add this to the docstring's field list: "and, when the harness sends one, `effort.level` as
  `effort` (round 4 C1)".

`api/routers/capture.py`:
- Change `from pydantic import BaseModel` to `from pydantic import BaseModel, Field`.
- Add this to `TranscriptCaptureRequest`:

```python
    # Round 4 C1: the Stop hook's `effort.level` for the reply it fired after —
    # validated by the capture writer (`agent_turns.clean_effort`), unknown dropped.
    effort: str | None = Field(default=None, max_length=32)
```

- In the `asyncio.to_thread(capture_transcript, ...)` call add `effort=req.effort,`.

- [ ] **Step 3: Green.**

Run: `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_capture_model_effort.py api/tests/test_transcript_extract.py api/tests/test_transcript_turn_stamps.py api/tests/test_episode_staging.py api/tests/test_capture_transcript.py api/tests/test_capture_hook.py api/tests/test_demo_capture.py api/tests/test_episode_writers_scrub.py -q -p no:cacheprovider`
→ 0 failed.

- [ ] **Step 4: Commit.**

```bash
cd <worktree> && git add api/services/agent_turns.py api/services/transcript_extract.py \
  api/services/episode_staging.py api/services/transcript_capture.py api/hooks/capture.py api/routers/capture.py \
  api/tests/test_capture_model_effort.py api/tests/test_transcript_turn_stamps.py api/tests/test_episode_staging.py && \
git commit -F - <<'MSG'
feat(capture): each agent turn keeps its model and reasoning effort (round 4 D1, C1, G49, G105)

The Stop-hook capture already reads the transcript (G105's one permitted
read); it now keeps exactly two more facts from an agent line — Claude Code's
message.model and top-level effort, Codex's turn_context model/effort — and
nothing else (thinking and reasoning text stay unread). They ride the turns
sidecar as model?/effort? on agent entries only, outside content_hash. The
hook forwards stdin effort.level; the transcript wins, the hook fills only the
last reply, and a re-capture keeps an earlier entry's values at the same
offset. The R-CS7 lint names agent_turns.py as the tolerant reader of the
two new keys. Rulings R4B-2..4.

<attribution lines from your session's system reminder>
MSG
```

---

### Task 3: C2 + the join — `recorded_ts` on MCP writes, and `turn_authorship` (not yet on the wire)

**Files:**
- Modify: `api/services/claims.py`, `api/services/episode_ids.py`, `api/services/agentic_write.py`,
  `api/services/progress.py`, `api/services/watch_record.py`, `api/services/mcp_tools.py`
- Create: `api/services/turn_authorship.py`
- Test: `api/tests/test_recorded_ts.py` (new), `api/tests/test_turn_authorship.py` (new),
  `api/tests/test_watch_record.py` (+1 test)

**Interfaces:**
- Produces: `Claim.recorded_ts: str | None` (YAML key `recorded_ts`, omitted when None),
  `episode_ids.utc_now_seconds() -> str` and `mcp_tools._now_ts() -> str`.
- Produces: the `recorded_ts=` keyword on `agentic_write.write_claim`, `agentic_write.retract_claim`,
  `agentic_write._withdrawal_record`, `progress.record_happening` / `set_milestone` / `advance` /
  `withdraw` and `watch_record.record`.
- Produces: `turn_authorship.turn_at(stamps, recorded_ts) -> (model, effort)`,
  `only_pair(stamps)` and `TurnAuthorship(memory_path, *, text=None)` with `.for_claim(claim,
  author_kind)` and `.for_span(ev)`, all returning `(model | None, effort | None)`.
- Consumes: `agent_turns.stamps`, `bank_index.files`, `evidence.span_status` / `turn_starts` and
  `episode_staging.MAX_TURN_STAMPS`.

- [ ] **Step 1: Failing tests.** Create `api/tests/test_recorded_ts.py`:

```python
"""Round 4 C2 (R4B-5): every claim an agent writes through the MCP seam — stdio
or remote — carries `recorded_ts`, the second it landed, so it can be joined to
the turn it was written in. Nothing else stamps one. Synthetic bank."""
from __future__ import annotations

import re

import pytest

from _synthetic_bank import _bank
from api.remote import catalog
from api.services import agentic_write, episode_ids, markdown_parser, mcp_tools
from api.services.claims import Claim, parse_claims

TS = "2026-09-24T10:31:02Z"


@pytest.fixture
def bank(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_tools, "_now_ts", lambda: TS)
    return _bank(tmp_path)


def _ctx(bank, **kw):
    return mcp_tools.ToolContext(memory_path=lambda: bank, session_id="ses_test", harness="claude-code", **kw)


def _claims(bank, stem="alpha-project"):
    return parse_claims(markdown_parser.parse(bank / "entities" / f"{stem}.md").body)


def test_the_clock_is_seconds_in_utc():
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", episode_ids.utc_now_seconds())


def test_a_stdio_write_is_stamped_to_the_second(bank):
    mcp_tools.write_claim(_ctx(bank), "alpha-project", "uses", "sqlite-vec", "agent", 0.8, None, None)
    [c] = [c for c in _claims(bank) if c.object == "sqlite-vec"]
    assert (c.recorded_ts, c.session_id) == (TS, "ses_test")


def test_a_remote_write_is_stamped_too(bank):
    ctx = _ctx(bank, connector_id="ab12cd34", available=catalog.tool_names_for(catalog.DEFAULT_SCOPES),
               read_surface="remote")
    mcp_tools.write_claim(ctx, "alpha-project", "uses", "duckdb", "agent", 0.8, None, None)
    [c] = [c for c in _claims(bank) if c.object == "duckdb"]
    assert (c.recorded_ts, c.origin) == (TS, "remote:ab12cd34")


def test_note_progress_is_stamped(bank):
    out = mcp_tools.note_progress(_ctx(bank), "alpha-project", "happened", "Shipped the alpha-project index", "done")
    assert "Not recorded" not in out, out
    [c] = [c for c in _claims(bank) if c.predicate == "happened"]
    assert c.recorded_ts == TS


def test_an_in_process_write_carries_none_and_writes_no_key(bank):
    agentic_write.write_claim(bank, "alpha-project", "uses", "postgres", observer="agent")
    [c] = [c for c in _claims(bank) if c.object == "postgres"]
    assert c.recorded_ts is None
    assert "recorded_ts" not in (bank / "entities" / "alpha-project.md").read_text(encoding="utf-8")


def test_a_reinforce_keeps_the_first_writers_second(bank, monkeypatch):
    mcp_tools.write_claim(_ctx(bank), "alpha-project", "uses", "sqlite-vec", "agent", 0.8, None, None)
    monkeypatch.setattr(mcp_tools, "_now_ts", lambda: "2026-09-25T08:00:00Z")
    mcp_tools.write_claim(_ctx(bank), "alpha-project", "uses", "sqlite-vec", "agent", 0.9, None, None)
    [c] = [c for c in _claims(bank) if c.object == "sqlite-vec"]
    assert c.recorded_ts == TS  # pairs with the first writer's session_id and authored_by


def test_the_field_round_trips_and_is_omitted_when_unset():
    assert Claim.from_dict(Claim(id="c1", text="t", recorded_ts=TS).to_dict()).recorded_ts == TS
    assert "recorded_ts" not in Claim(id="c2", text="t").to_dict()
```

Append this test to `api/tests/test_watch_record.py`:

```python
def test_a_watch_claim_is_stamped_to_the_second(saved, monkeypatch):
    """Round 4 C2: `cicada_record_watch` is an MCP write like any other."""
    server, memory = saved
    monkeypatch.setattr(mcp_tools, "_now_ts", lambda: "2026-09-24T10:31:02Z")
    eid, _ep, cid = _ids(_record(server))
    assert _claim(memory, eid, cid).recorded_ts == "2026-09-24T10:31:02Z"
```

Create `api/tests/test_turn_authorship.py`:

```python
"""Round 4 C3 (R4B-6, R4B-7): which model and effort wrote a harness claim —
joined at read from the capture episode's per-turn sidecar, never stored, never
guessed. Pure rules first, then over a synthetic bank."""
from __future__ import annotations

import pytest

from api.services import agent_turns, bank_index, episode_staging, evidence, markdown_parser
from api.services import turn_authorship as ta
from api.services.claims import Claim, Evidence

SID = "22222222-3333-4444-8555-666666666666"
EP = "ep_2026-09-03_001"
BODY = ("user: Should alpha-project move to sqlite-vec?\n"
        "assistant: Yes — bob-example agreed last week.\n"
        "user: Then ship it.\n"
        "assistant: Shipped to example.com.")
STARTS = [0] + [i + 1 for i, ch in enumerate(BODY) if ch == "\n"]
SIDECAR = [
    {"offset": STARTS[0], "ts": "2026-09-03T10:00:00+00:00", "speaker": "user"},
    {"offset": STARTS[1], "ts": "2026-09-03T10:00:05+00:00", "speaker": "assistant",
     "model": "claude-opus-5-5", "effort": "xhigh"},
    {"offset": STARTS[2], "ts": "2026-09-03T10:05:00.600000+00:00", "speaker": "user"},
    {"offset": STARTS[3], "ts": "2026-09-03T10:05:30+00:00", "speaker": "assistant",
     "model": "claude-sonnet-5", "effort": "low"},
]


def _stamps(entries=SIDECAR):
    return agent_turns.stamps({"turns": entries})


@pytest.mark.parametrize("at, expected", [
    ("2026-09-03T10:00:03Z", ("claude-opus-5-5", "xhigh")),   # written during the first turn
    ("2026-09-03T10:05:00Z", ("claude-sonnet-5", "low")),     # the question's own second (both floored)
    ("2026-09-03T10:07:00Z", ("claude-sonnet-5", "low")),     # still the last question's turn
    ("2026-09-03T09:59:59Z", (None, None)),                   # before anyone asked
    ("not a time", (None, None)),
])
def test_a_write_belongs_to_the_turn_it_happened_in(at, expected):
    assert ta.turn_at(_stamps(), at) == expected


def test_a_question_with_no_kept_reply_answers_nothing():
    only_tools = [SIDECAR[0], SIDECAR[2], SIDECAR[3]]  # the first question's reply was tool calls only
    assert ta.turn_at(_stamps(only_tools), "2026-09-03T10:00:30Z") == (None, None)


def test_past_the_head_stable_cap_nothing_is_claimed(monkeypatch):
    monkeypatch.setattr(episode_staging, "MAX_TURN_STAMPS", 4)
    assert ta.turn_at(_stamps(), "2026-09-03T10:06:00Z") == (None, None)
    assert ta.turn_at(_stamps(), "2026-09-03T10:00:03Z") == ("claude-opus-5-5", "xhigh")


def test_without_recorded_ts_only_a_one_model_session_answers():
    assert ta.only_pair(_stamps()) == (None, None)
    assert ta.only_pair(_stamps(SIDECAR[:2])) == ("claude-opus-5-5", "xhigh")


def test_the_sidecar_reader_is_tolerant_and_cleans():
    raw = [{"offset": 0, "ts": "x", "speaker": "user", "model": "claude-opus-5-5"},   # a person names no model
           {"offset": 5, "ts": "y", "speaker": "assistant", "model": "<synthetic>", "effort": "HIGH"},
           {"offset": "bad"}, "junk", {"offset": 5, "speaker": "assistant", "model": "dup"}]
    assert [(s.offset, s.model, s.effort) for s in agent_turns.stamps({"turns": raw})] == [
        (0, None, None), (5, None, "high")]
    assert agent_turns.stamps({"turns": 7}) == []  # a pre-PJ-4 count


@pytest.fixture
def memory(tmp_path):
    m = tmp_path / "memory"
    (m / "episodes").mkdir(parents=True)
    (m / "entities").mkdir()
    markdown_parser.write(m / "episodes" / f"{EP}.md", {
        "id": EP, "timestamp": "2026-09-03T10:00:00+00:00", "source": "claude-code", "origin": "claude-code",
        "title": "Sync race", "session_id": SID, "harness": "claude-code", "capture_kind": "transcript",
        "processed": True, "turns": SIDECAR}, BODY)
    # An MCP episode of the SAME session is never the capture (R3): its sidecar is ignored.
    markdown_parser.write(m / "episodes" / "ep_2026-09-03_002.md", {
        "id": "ep_2026-09-03_002", "session_id": SID, "harness": "claude-code",
        "turns": [{"offset": 0, "ts": "2026-09-03T10:05:05+00:00", "speaker": "assistant", "model": "decoy-1"}]},
        "assistant: a note")
    bank_index.invalidate()
    return m


def _span(quote, *, digest=None):
    start = BODY.index(quote)
    return Evidence(episode=EP, start=start, end=start + len(quote), kind="assistant",
                    hash=digest or evidence.body_hash(BODY))


def _claim(**kw):
    base = dict(id="clm_alpha", text="alpha-project uses sqlite-vec", subject="alpha-project", predicate="uses",
                object="sqlite-vec", authored_by="claude-code", session_id=SID, recorded_ts="2026-09-03T10:05:10Z")
    base.update(kw)
    return Claim(**base)


def test_a_harness_claim_joins_to_its_sessions_capture_turn(memory):
    turns = ta.TurnAuthorship(memory)
    assert turns.for_claim(_claim(), "harness") == ("claude-sonnet-5", "low")
    assert turns.for_claim(_claim(recorded_ts=None), "harness") == (None, None)       # two models: no guess
    assert turns.for_claim(_claim(session_id="ses_2026-09-03_nomatch"), "harness") == (None, None)
    assert turns.for_claim(_claim(), "model") == (None, None)   # a Sleep claim's model is its Cicada-Author


def test_an_assistant_span_carries_its_turns_model(memory):
    turns = ta.TurnAuthorship(memory)
    assert turns.for_span(_span("Yes — bob-example agreed")) == ("claude-opus-5-5", "xhigh")
    assert turns.for_span(_span("Shipped to example.com")) == ("claude-sonnet-5", "low")
    assert turns.for_span(_span("Yes — bob-example", digest="000000000000")) == (None, None)  # stale: never
    person = Evidence(episode=EP, start=0, end=5, kind="user", hash=evidence.body_hash(BODY))
    assert turns.for_span(person) == (None, None)


def test_a_body_is_read_once_and_only_where_a_sidecar_names_a_model(memory):
    markdown_parser.write(memory / "episodes" / "ep_2026-09-04_001.md", {
        "id": "ep_2026-09-04_001",
        "turns": [{"offset": 0, "ts": "2026-09-04T09:00:00+00:00", "speaker": "assistant"}]}, "assistant: hi")
    bank_index.invalidate()
    reads: list[str] = []
    turns = ta.TurnAuthorship(memory, text=lambda ep: reads.append(ep) or BODY)
    bare = Evidence(episode="ep_2026-09-04_001", start=11, end=13, kind="assistant", hash="")
    assert turns.for_span(bare) == (None, None) and reads == []
    turns.for_span(_span("Yes — bob-example"))
    turns.for_span(_span("Shipped"))
    assert reads == [EP]
```

Run: `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_recorded_ts.py api/tests/test_turn_authorship.py api/tests/test_watch_record.py -q -p no:cacheprovider`
→ red (`_now_ts`, `recorded_ts` and `turn_authorship` do not exist).

- [ ] **Step 2: Implement `recorded_ts`.**

`api/services/claims.py`, at the END of the `Claim` field list (after `date_basis`; appended so
no positional constructor shifts):

```python
    # Round 4 C2 (G49 lifted for harness writes, TODO ruling 11): the second a
    # claim was written through the MCP seam (stdio or remote),
    # `YYYY-MM-DDTHH:MM:SSZ`, beside the day-granular `recorded_at`. With the
    # first-writer `session_id` it is what `turn_authorship` joins to the
    # captured turn the write happened in; a reinforce moves neither (R4B-5).
    # Omitted from the YAML when unset (R7's reason).
    recorded_ts: str | None = None
```

In `to_dict`, before `return data`:

```python
        if data.get("recorded_ts") is None:
            data.pop("recorded_ts", None)
```

In `from_dict`, add `recorded_ts=_opt_str(data.get("recorded_ts")),` after `date_basis=...`.

`api/services/episode_ids.py`, after `utc_now_iso`:

```python
def utc_now_seconds() -> str:
    """Now as `YYYY-MM-DDTHH:MM:SSZ` — the shape of a claim's `recorded_ts`
    (round 4 C2). Seconds on purpose: it is compared with a turn's time floored
    to the second (`turn_authorship`), and a sub-second stamp would claim a
    precision the join does not use."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
```

`api/services/agentic_write.py`:
- `write_claim` gains the keyword `recorded_ts: str | None = None` (after `today`). Add this
  docstring paragraph:
  "``recorded_ts`` (round 4 C2, R4B-5): the second an MCP write landed, passed by the one MCP
  seam (`mcp_tools`) and nothing else; stored beside ``session_id`` so the read path can join the
  claim to its captured turn."
- In `Claim(...)` add `recorded_ts=(recorded_ts or "").strip() or None,`.
- `_withdrawal_record` gains `recorded_ts: str | None = None`, and its `Claim(...)` gets
  `recorded_ts=(recorded_ts or "").strip() or None,`.
- `retract_claim` gains `recorded_ts: str | None = None` and passes `recorded_ts=recorded_ts` to
  `_withdrawal_record`.

`api/services/progress.py`:
- `record_happening`, `set_milestone`, `advance` and `withdraw` each gain the keyword
  `recorded_ts: str | None = None`.
- `record_happening` / `set_milestone`: add `recorded_ts=(recorded_ts or "").strip() or None,` to
  their `Claim(...)`.
- `advance`: add the same line to the `Claim(...)` inside `build`.
- `withdraw`: pass `recorded_ts=recorded_ts` to `_withdrawal_record`.

`api/services/watch_record.py`: `record` gains `recorded_ts: str | None = None` and passes
`recorded_ts=recorded_ts` to `agentic_write.write_claim`.

`api/services/mcp_tools.py`, after `_demo_refusal`:

```python
def _now_ts() -> str:
    """The second an agent's write lands (round 4 C2) — one clock for every MCP
    write tool, stdio and remote alike, patchable in tests like `_now_in`."""
    return episode_ids.utc_now_seconds()
```

Then pass it at each write:
- `write_claim` → `agentic_write.write_claim(..., recorded_ts=_now_ts())`
- `record_watch` → `watch_record.record(..., recorded_ts=_now_ts())`
- `note_progress`: add `recorded_ts=_now_ts()` to the `common = dict(...)`
- `retract_claim`: both branches, `progress.withdraw(..., recorded_ts=_now_ts())` and
  `agentic_write.retract_claim(..., recorded_ts=_now_ts())`

- [ ] **Step 3: Implement the join.** Create `api/services/turn_authorship.py`:

```python
"""Which model, at which reasoning effort, wrote a harness claim — joined at
read, never stored (round 4 D1, contracts C3/C4; G49's reservation lifted for
harness writes, TODO ruling 11).

G49 kept a conversation's model reserved because nothing that wrote memory
recorded one. Round 4 records it where it is already known: the Stop-hook
capture keeps each agent turn's `model`/`effort` in the episode's `turns`
sidecar (C1), and every claim written through the MCP seam carries
`recorded_ts` (C2). This module joins the two, per request, from bank files:

* a claim → its first writer's `session_id` → that session's capture episode
  (`capture_kind: transcript`; an MCP episode of the same session never is) →
  the last person's turn at or before `recorded_ts` → the agent turn that
  answered it (the next agent entry before the next person's). No such turn →
  null. No `recorded_ts` (written before C2) → the session's only model, when it
  used exactly one (R4B-6).
* an evidence span of kind `assistant` → the turn its start falls in, by the
  body's own turn starts, unless the span is stale (R4B-7).

Never self-reported: an agent asked for its model can only guess, and a guess
in provenance is worse than a blank (D1). Only author kind `harness` is joined —
a Sleep claim's model is its `Cicada-Author`. Engine-free: `bank_index`'s cached
frontmatter, and at most one body read per cited episode per request, only for
an episode whose sidecar names a model.
"""

from __future__ import annotations

import bisect
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from api.services import agent_turns, bank_index, episode_staging, evidence, git_service
from api.services.claims import Claim, Evidence

#: `transcript_capture.CAPTURE_KIND`, spelled here: the read paths must never
#: import the capture writer (`test_the_provenance_module_is_engine_free`).
CAPTURE_KIND = "transcript"

Pair = tuple[str | None, str | None]
NONE: Pair = (None, None)


def _second(value) -> datetime | None:
    """An aware instant floored to the second, or None. `recorded_ts` has second
    precision and a turn's `ts` has milliseconds, so both sides are floored: a
    question asked at 10:05:00.600 and a write stamped 10:05:00 are the same
    second, and the write belongs to that question's turn (R4B-6)."""
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value or "").strip())
        except ValueError:
            return None
    if dt.tzinfo is None:
        return None
    return dt.astimezone(timezone.utc).replace(microsecond=0)


def turn_at(stamps: list[agent_turns.Stamp], recorded_ts) -> Pair:
    """C3's join over one session's sidecar. Pure."""
    moment = _second(recorded_ts)
    if moment is None or not stamps:
        return NONE
    if len(stamps) >= episode_staging.MAX_TURN_STAMPS:
        # Turns past the head-stable cap carry no stamp: a write after the last
        # stamped turn could belong to any of them.
        last = _second(stamps[-1].ts)
        if last is None or moment >= last:
            return NONE
    asked = None
    for i, s in enumerate(stamps):
        if s.speaker != "user":
            continue
        at = _second(s.ts)
        if at is None:
            continue
        if at > moment:
            break
        asked = i
    if asked is None:
        return NONE
    for s in stamps[asked + 1:]:
        if s.speaker == "user":
            return NONE          # that question got no kept reply (tool calls only)
        if s.speaker == "assistant":
            return (s.model, s.effort)
    return NONE                  # the reply is not captured yet — the next Stop adds it


def only_pair(stamps: list[agent_turns.Stamp]) -> Pair:
    """A claim with no `recorded_ts`: the session's model when it used exactly
    one, and its effort by the same rule, independently."""
    models = {s.model for s in stamps if s.speaker == "assistant" and s.model}
    efforts = {s.effort for s in stamps if s.speaker == "assistant" and s.effort}
    return (next(iter(models)) if len(models) == 1 else None,
            next(iter(efforts)) if len(efforts) == 1 else None)


class TurnAuthorship:
    """One request's join. Build one per request and pass it to every
    `claim_to_model` call; `text` shares the caller's body cache (the timeline's
    `episode_text`, provenance's `_Episodes.body`) so a body is read once."""

    def __init__(self, memory_path: Path | None, *, text: Callable[[str], str | None] | None = None):
        self._path = Path(memory_path) if memory_path is not None else None
        self._text = text
        self._files: dict[str, bank_index.IndexedFile] | None = None
        self._by_session: dict[str, str] | None = None
        self._stamps: dict[str, list[agent_turns.Stamp]] = {}
        self._bodies: dict[str, str | None] = {}
        self._starts: dict[str, list[int]] = {}

    def _index(self) -> dict[str, bank_index.IndexedFile]:
        if self._files is None:
            self._files = ({f.stem: f for f in bank_index.files(self._path, "episodes")}
                           if self._path is not None else {})
        return self._files

    def _capture_of(self, session_id: str) -> str | None:
        if self._by_session is None:
            self._by_session = {}
            for stem, f in sorted(self._index().items()):
                fm = f.frontmatter or {}
                sid = str(fm.get("session_id") or "").strip()
                if sid and fm.get("capture_kind") == CAPTURE_KIND:
                    self._by_session.setdefault(sid, stem)
        return self._by_session.get(session_id)

    def stamps(self, episode: str) -> list[agent_turns.Stamp]:
        if episode not in self._stamps:
            f = self._index().get(episode)
            self._stamps[episode] = agent_turns.stamps(f.frontmatter if f is not None else None)
        return self._stamps[episode]

    def _body(self, episode: str) -> str | None:
        if episode not in self._bodies:
            if self._text is not None:
                self._bodies[episode] = self._text(episode)
            else:
                f = self._index().get(episode)
                try:
                    self._bodies[episode] = f.body() if f is not None else None
                except Exception:  # noqa: BLE001 — one unreadable episode never fails a read
                    self._bodies[episode] = None
        return self._bodies[episode]

    def for_claim(self, claim: Claim, author_kind: str) -> Pair:
        if author_kind != git_service.HARNESS_KIND:
            return NONE
        sid = (claim.session_id or "").strip()
        episode = self._capture_of(sid) if sid else None
        if episode is None:
            return NONE
        stamps = self.stamps(episode)
        return turn_at(stamps, claim.recorded_ts) if claim.recorded_ts else only_pair(stamps)

    def for_span(self, ev: Evidence) -> Pair:
        if ev.kind != "assistant" or not ev.is_span() or not evidence.is_episode_id(ev.episode):
            return NONE
        stamps = self.stamps(ev.episode)
        if not any(s.model or s.effort for s in stamps):
            return NONE          # nothing to find: no body read
        body = self._body(ev.episode)
        if body is None or ev.end > len(body):
            return NONE
        if evidence.span_status(body, end=ev.end, hash=ev.hash) == evidence.SPAN_STALE:
            return NONE          # stale never answers (§4.9)
        starts = self._starts.setdefault(ev.episode, evidence.turn_starts(body))
        i = bisect.bisect_right(starts, ev.start) - 1
        if i < 0:
            return NONE
        hit = next((s for s in stamps if s.offset == starts[i]), None)
        return (hit.model, hit.effort) if hit is not None and hit.speaker == "assistant" else NONE
```

- [ ] **Step 4: Green.**

Run: `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_recorded_ts.py api/tests/test_turn_authorship.py api/tests/test_watch_record.py api/tests/test_note_progress_tool.py api/tests/test_remote_runtime.py api/tests/test_agent_provenance.py api/tests/test_mcp_stdio_golden.py api/tests/test_projects_app_fixture.py api/tests/test_claims_evidence.py -q -p no:cacheprovider`
→ 0 failed.
- The golden replies must stay byte-identical: no reply prints `recorded_ts`.
- The app fixture must not move: the demo passes no `recorded_ts`, and the wire does not serve it
  yet.

Then run the full suite once:
`cd <worktree> && api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider`.
- A test that pins a whole claim written through an MCP tool (its dict or its fence text) now also
  sees `recorded_ts` on the real clock.
- Fix such a test by patching `mcp_tools._now_ts` to a constant and expecting that value. Never
  drop the field to make it pass.

- [ ] **Step 5: Commit.**

```bash
cd <worktree> && git add api/services/claims.py api/services/episode_ids.py api/services/agentic_write.py \
  api/services/progress.py api/services/watch_record.py api/services/mcp_tools.py api/services/turn_authorship.py \
  api/tests/test_recorded_ts.py api/tests/test_turn_authorship.py api/tests/test_watch_record.py && \
git commit -F - <<'MSG'
feat(claims): recorded_ts on MCP writes + the turn join, engine-free (round 4 C2/C3, G49, G118)

Every claim an agent writes through the MCP seam (stdio and remote share
mcp_tools) carries recorded_ts, the second it landed; in-process writers
(Telegram, Wispr, the Projects page, the demo) stamp none, so the demo wire
stays byte-stable. turn_authorship joins a harness claim to its session's
capture turn (the last question at or before recorded_ts, the reply that
answered it) and an assistant span to the turn it falls in — per request,
from bank files, one body read per cited episode. Not on the wire yet.
Rulings R4B-5..7, R4B-16.

<attribution lines from your session's system reminder>
MSG
```

---

### Task 4: C3 + C4 — the wire: `authorModel`/`authorEffort`, span models, contributor models, the Reader's `agent`

**Files:**
- Modify: `api/models/schemas.py`, `api/services/turn_authorship.py` (`evidence_model`),
  `api/services/transclusion_resolver.py`, `api/routers/claims.py`, `api/routers/projects.py`,
  `api/services/project_timeline.py`, `api/services/provenance.py`, `api/routers/episodes.py`,
  `api/services/git_service.py`
- Modify (tests): `api/tests/test_agent_labels.py:72,74`
- Regenerate: `app/CicadaApp/Tests/fixtures/projects-demo.json`
- Test: `api/tests/test_turn_authorship_wire.py` (new)

**Interfaces:**
- Produces (C3): `ClaimModel` gains `recordedTs`, `authorModel` and `authorEffort`.
  `EvidenceModel` gains `model`/`effort`, derived at read and never stored.
- Produces (C4): `ProvenanceContributor.models: [{model, effort?, beliefs}]`,
  `EpisodeText.agent: {model?, effort?} | null` and `EpisodeTurn.model/effort`.
- Produces: `claim_to_model(claim, *, turns)` (required keyword), `turn_authorship.evidence_model(ev, turns)`
  and `git_service.AUTHOR_SHAPE = "harness-2"`, folded into five ETags.
- Consumes: `TurnAuthorship`, `agent_turns.stamps`.

- [ ] **Step 1: Failing tests.** Create `api/tests/test_turn_authorship_wire.py`:

```python
"""Round 4 C3/C4 on the wire: a harness claim names the model and effort of the
turn it was written in; an assistant span names its turn's; a harness
contributor lists its models; the Reader's text names each agent turn's; every
read that now carries a model moves its ETag with `AUTHOR_SHAPE`. Synthetic."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from _synthetic_bank import _bank
from api import config, main
from api.services import bank_index, evidence, git_service, handshake, markdown_parser, search_index
from api.services import transclusion_resolver
from api.services.claims import Claim, Evidence, parse_claims, write_claims

SID = "22222222-3333-4444-8555-666666666666"
EP = "ep_2026-09-03_001"
BODY = ("user: Should alpha-project move to sqlite-vec?\n"
        "assistant: Yes — bob-example agreed last week.\n"
        "user: Then ship it.\n"
        "assistant: Shipped to example.com.")
STARTS = [0] + [i + 1 for i, ch in enumerate(BODY) if ch == "\n"]
SIDECAR = [
    {"offset": STARTS[0], "ts": "2026-09-03T10:00:00+00:00", "speaker": "user"},
    {"offset": STARTS[1], "ts": "2026-09-03T10:00:05+00:00", "speaker": "assistant",
     "model": "claude-opus-5-5", "effort": "xhigh"},
    {"offset": STARTS[2], "ts": "2026-09-03T10:05:00+00:00", "speaker": "user"},
    {"offset": STARTS[3], "ts": "2026-09-03T10:05:30+00:00", "speaker": "assistant",
     "model": "claude-sonnet-5", "effort": "low"},
]
QUOTE = "Yes — bob-example agreed last week."


def _span() -> Evidence:
    start = BODY.index(QUOTE)
    return Evidence(episode=EP, start=start, end=start + len(QUOTE), kind="assistant", hash=evidence.body_hash(BODY))


@pytest.fixture
def client(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    markdown_parser.write(memory / "episodes" / f"{EP}.md", {
        "id": EP, "timestamp": "2026-09-03T10:00:00+00:00", "source": "claude-code", "origin": "claude-code",
        "title": "Sync race", "session_id": SID, "harness": "claude-code", "capture_kind": "transcript",
        "processed": True, "turns": SIDECAR}, BODY)
    page = memory / "entities" / "alpha-project.md"
    parsed = markdown_parser.parse(page)
    claims = parse_claims(parsed.body) + [
        Claim(id="clm_alpha_agent", text="alpha-project uses sqlite-vec", subject="alpha-project", predicate="uses",
              object="sqlite-vec", observer="agent", valid_from="2026-09-03", recorded_at="2026-09-03",
              authored_by="claude-code", origin="mcp", session_id=SID, recorded_ts="2026-09-03T10:05:10Z",
              evidence=[_span()], source_episodes=[EP]),
        Claim(id="clm_alpha_sleep", text="alpha-project decided to ship", subject="alpha-project",
              predicate="decided", object="ship", observer="agent", valid_from="2026-09-03",
              recorded_at="2026-09-03", authored_by="gpt-5.4-mini", evidence=[_span()], source_episodes=[EP]),
    ]
    markdown_parser.write(page, parsed.frontmatter, write_claims(parsed.body, claims))
    bank_index.invalidate()
    search_index.ensure_fresh(memory, wait=True, max_age_s=0)  # `/projects` pins an ETag only when ready
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setattr(handshake, "local_timezone", lambda: "UTC")
    config.get_settings.cache_clear()
    yield TestClient(main.app), memory
    config.get_settings.cache_clear()


def test_the_claim_wire_names_the_turn_a_harness_write_happened_in(client):
    c, _ = client
    claims = {x["id"]: x for x in c.get("/entities/alpha-project/claims").json()["claims"]}
    agent, sleep = claims["clm_alpha_agent"], claims["clm_alpha_sleep"]
    assert (agent["authorKind"], agent["authorModel"], agent["authorEffort"], agent["recordedTs"]) == (
        "harness", "claude-sonnet-5", "low", "2026-09-03T10:05:10Z")
    assert (agent["evidence"][0]["model"], agent["evidence"][0]["effort"]) == ("claude-opus-5-5", "xhigh")
    assert (sleep["authorKind"], sleep["authorModel"], sleep["authorEffort"]) == ("model", None, None)
    assert sleep["evidence"][0]["model"] == "claude-opus-5-5"  # a span is its turn's, whoever cited it


def test_timeline_and_transclusion_serve_the_same_fields(client):
    c, _ = client
    [row] = c.get("/entities/alpha-project/timeline?predicate=uses&context=general").json()["claims"]
    assert (row["authorModel"], row["authorEffort"]) == ("claude-sonnet-5", "low")
    [tr] = c.get("/transclude?ref=claim:clm_alpha_agent").json()["claims"]
    assert (tr["authorModel"], tr["evidence"][0]["model"]) == ("claude-sonnet-5", "claude-opus-5-5")


def test_a_harness_contributor_lists_its_models(client):
    c, _ = client
    rows = {r["author"]: r for r in c.get("/entities/alpha-project/provenance").json()["contributors"]}
    assert rows["claude-code"]["models"] == [{"model": "claude-sonnet-5", "effort": "low", "beliefs": 1}]
    assert rows["gpt-5.4-mini"]["models"] == []


def test_the_reader_text_names_each_agent_turn(client):
    c, _ = client
    body = c.get(f"/episodes/{EP}/text").json()
    assert body["agent"] == {"model": "claude-sonnet-5", "effort": "low"}
    assert [(t["role"], t["model"], t["effort"]) for t in body["turns"]] == [
        ("user", None, None), ("assistant", "claude-opus-5-5", "xhigh"),
        ("user", None, None), ("assistant", "claude-sonnet-5", "low")]


def test_citations_carry_the_span_model(client):
    c, _ = client
    rows = c.get(f"/episodes/{EP}/citations").json()["citations"]
    assert {r["evidence"]["model"] for r in rows if r["kind"] == "assistant"} == {"claude-opus-5-5"}


def test_every_read_that_carries_a_model_moves_with_the_author_shape(client, monkeypatch):
    c, _ = client
    urls = (f"/episodes/{EP}/text", f"/episodes/{EP}/citations", "/entities/alpha-project/provenance",
            "/projects", "/projects/alpha-project/timeline")
    tags = {}
    for url in urls:
        tags[url] = c.get(url).headers.get("etag")
        assert tags[url], url
        assert c.get(url, headers={"If-None-Match": tags[url]}).status_code == 304, url
    monkeypatch.setattr(git_service, "AUTHOR_SHAPE", "shape-test")
    for url in urls:
        assert c.get(url, headers={"If-None-Match": tags[url]}).status_code == 200, url


def test_claim_to_model_cannot_forget_the_join():
    with pytest.raises(TypeError):
        transclusion_resolver.claim_to_model(Claim(id="c", text="t"))
```

Run: `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_turn_authorship_wire.py -q -p no:cacheprovider` → red.

- [ ] **Step 2: Schemas.** In `api/models/schemas.py`:

`EvidenceModel`, after `hash: str = ""`:

```python
    # Round 4 C3 — derived at read, never stored: for a span of kind `assistant`,
    # the model and reasoning effort of the agent turn its offset falls in
    # (`turn_authorship.TurnAuthorship.for_span`); null everywhere else.
    model: Optional[str] = None
    effort: Optional[str] = None
```

`ClaimModel`, after `expected_end: Optional[str] = None`:

```python
    # Round 4 C2/C3 — additive. `recorded_ts` is stored on MCP writes only;
    # `author_model`/`author_effort` are joined at read for a harness write
    # (`turn_authorship.TurnAuthorship.for_claim`) and null when no captured
    # turn answers — the app then says the model wasn't shared.
    recorded_ts: Optional[str] = None
    author_model: Optional[str] = None
    author_effort: Optional[str] = None
```

`EpisodeTurn`, after `t: Optional[int] = None`:

```python
    # Round 4 C4: an agent turn's model and reasoning effort, from the episode's
    # `turns` sidecar entry at exactly this turn's start; null otherwise.
    model: Optional[str] = None
    effort: Optional[str] = None
```

Before `class EpisodeText`:

```python
class EpisodeAgent(CamelModel):
    """Round 4 C4: the most recent agent turn's model and effort (R4B-15). The
    field is null when that turn names neither; an older turn never stands in."""

    model: Optional[str] = None
    effort: Optional[str] = None
```

`EpisodeText`, after `focus: Optional[EpisodeFocus] = None`: `agent: Optional[EpisodeAgent] = None`.

Before `class ProvenanceContributor`:

```python
class ProvenanceModel(CamelModel):
    """Round 4 C4: one model (and effort) a harness contributor wrote with, and
    how many of the page's current beliefs it wrote that way."""

    model: str
    effort: Optional[str] = None
    beliefs: int = 0
```

`ProvenanceContributor`, after `commits: int = 0`:

```python
    # Round 4 C4: a `harness` contributor's joined turn models; empty when the
    # app did not share them (no capture hook, or a Codex MCP session).
    models: list[ProvenanceModel] = []
```

- [ ] **Step 3: The builder and its call sites.**

`api/services/turn_authorship.py`:
- Add `from api.models.schemas import EvidenceModel` to the imports.
- Append:

```python
def evidence_model(ev: Evidence, turns: TurnAuthorship | None) -> EvidenceModel:
    """One span on the wire (G118) with its turn's model (C3). `turns=None`
    serves the two fields as null — a caller with no bank to read."""
    model, effort = turns.for_span(ev) if turns is not None else NONE
    return EvidenceModel(**ev.to_dict(), model=model, effort=effort)
```

`api/services/transclusion_resolver.py`:
- The import becomes `from api.services import git_service, markdown_parser, turn_authorship`.
- Rewrite `claim_to_model`:

```python
def claim_to_model(claim: Claim, *, turns: turn_authorship.TurnAuthorship | None) -> ClaimModel:
    """The ONE ``Claim`` → ``ClaimModel`` builder. ``routers/claims._claim_to_model``
    delegates here, so ``/entities/{id}/claims``, ``/timeline`` and
    ``/transclude`` can never ship two shapes of one claim — G118 slice 2
    (R-PB13) found the two copies drifting the moment author fields were added
    to only one. ``author_kind``/``author_provider`` come from
    ``git_service.author_identity``, the rule the contributors strip reads.

    ``turns`` (round 4 C3, R4B-8) is the request's join: a harness write's
    ``author_model``/``author_effort`` and each assistant span's model come from
    it. Required, so no call site can forget the join; ``None`` only where there
    is no bank to read, which serves those fields as null."""
    author = git_service.canonical_author(claim.authored_by)
    author_kind, author_provider = git_service.author_identity(author)
    model, effort = turns.for_claim(claim, author_kind) if turns is not None else turn_authorship.NONE
    return ClaimModel(
        id=claim.id,
        text=claim.text,
        subject=claim.subject,
        predicate=claim.predicate,
        object=claim.object,
        object_kind=claim.object_kind,
        observer=claim.observer,
        context=claim.context,
        epistemic=claim.epistemic,
        source_trust=claim.source_trust,
        confidence=claim.confidence,
        valid_from=claim.valid_from or "",
        valid_to=claim.valid_to,
        superseded_by=claim.superseded_by,
        supersedes=claim.supersedes,
        source_episodes=claim.source_episodes,
        premises=claim.premises,
        authored_by=author,
        origin=claim.origin,
        evidence=[turn_authorship.evidence_model(e, turns) for e in (claim.evidence or [])],
        # G118 slice 2 (R-PB13) — additive.
        session_ids=claim.all_session_ids(),
        recorded_at=claim.recorded_at,
        author_kind=author_kind,
        author_provider=author_provider,
        # G141 §4.1 — additive: the event fields and the stated end.
        status=claim.status,
        target=claim.target,
        participants=[ParticipantModel(**p) for p in (claim.participants or [])],
        date_basis=claim.date_basis,
        expected_end=claim.expected_end,
        # Round 4 C2/C3 — additive.
        recorded_ts=claim.recorded_ts,
        author_model=model,
        author_effort=effort,
    )
```

- Remove `EvidenceModel` from the schemas import. After this rewrite nothing else in the file uses
  it (`ruff`/pyflakes would flag it otherwise).
- In `_resolve_claim`, set `turns = turn_authorship.TurnAuthorship(memory_path)` before the loop,
  and use `claims=[claim_to_model(claim, turns=turns)]`.
- In `_resolve_facet`, set `turns = turn_authorship.TurnAuthorship(memory_path)`, and use
  `claims=[claim_to_model(c, turns=turns) for c in facet_claims]`.

`api/routers/claims.py`:
- The imports gain `turn_authorship`.
- `_claim_to_model(c: Claim, turns) -> ClaimModel:` returns
  `transclusion_resolver.claim_to_model(c, turns=turns)`.
- In `get_entity_claims`: `turns = turn_authorship.TurnAuthorship(settings.memory_path)` and
  `ClaimListResponse(claims=[_claim_to_model(c, turns) for c in claims])`.
- Make the same change in `get_entity_timeline`.

`api/routers/projects.py`:
- The imports gain `turn_authorship` (next to `git_service`).
- In `_models`, set `turns = turn_authorship.TurnAuthorship(memory_path)` before the loop and use
  `out.append(claim_to_model(c, turns=turns))`.
- Both ETags fold the author shape (R4B-9):
  - `extra=f"projects|{project_timeline.PROJECT_SHAPE}|{git_service.AUTHOR_SHAPE}|{tz}"`
  - `extra=f"project|{stem}|{since_day or ''}|{project_timeline.PROJECT_SHAPE}|{git_service.AUTHOR_SHAPE}|{tz}"`
  - Add one line to the module docstring's ETag sentence: "…and `git_service.AUTHOR_SHAPE`
    (round 4: the bodies carry claim author kinds and turn models)".

`api/services/project_timeline.py`:
- Add `turn_authorship` to the `from api.services import (...)` list.
- In `_Bank.__init__`, at the end:

```python
        # Round 4 C3: one join per request, sharing this request's episode bodies.
        self.turns = turn_authorship.TurnAuthorship(self.path, text=self.episode_text)
```

- Make every `claim_to_model(...)` in the module pass `turns=bank.turns`:
  `chain=[claim_to_model(x, turns=bank.turns) for x in chain]`, the two `chain=[claim_to_model(c, turns=bank.turns)]`,
  and `claim=claim_to_model(shown, turns=bank.turns)`.

`api/services/provenance.py`:
- The imports: add `EpisodeAgent` and `ProvenanceModel` to the schemas import, and add
  `agent_turns, turn_authorship` to the services import.
- `episode_document`: directly after
  `spans = evidence.turns(text, page=not is_episode, stamps=stamps, override=override)` and
  BEFORE the `truncated` cut, add:

```python
    # Round 4 C4: an agent turn's model/effort is its sidecar entry at exactly
    # the turn's start (the entry the capture wrote); never on a person's turn.
    agents = {s.offset: s for s in agent_turns.stamps(fm) if s.speaker == "assistant"} if is_episode else {}
    # R4B-15: `agent` is the most recent agent turn's — of the WHOLE document,
    # read before the Reader's cut — and null when that turn names neither; an
    # older turn's model never stands in for it (D1: never guessed).
    last = next((t for t in reversed(spans) if t.role == "assistant"), None)
    stamp = agents.get(last.start) if last is not None else None
    agent = EpisodeAgent(model=stamp.model, effort=stamp.effort) if stamp and (stamp.model or stamp.effort) else None
```

  Then, after the `truncated` block, replace `turns=[EpisodeTurn(**asdict(t)) for t in spans],`
  by computing, before the `return`:

```python
    turn_models: list[EpisodeTurn] = []
    for t in spans:
        s = agents.get(t.start) if t.role == "assistant" else None
        turn_models.append(EpisodeTurn(**asdict(t), model=s.model if s else None, effort=s.effort if s else None))
```

  and in the `EpisodeText(...)` use `turns=turn_models,` plus `agent=agent,`.
- `entity_provenance`: directly after `docs = _Episodes(memory_path)`:

```python
    # Round 4 C4: a harness contributor's models, joined per current claim
    # (R4B-6); a Sleep author is a model already and is never joined.
    turns = turn_authorship.TurnAuthorship(memory_path, text=docs.body)
    models: dict[str, Counter] = {}
    for c in current:
        author = git_service.canonical_author(c.authored_by)
        model, effort = turns.for_claim(c, git_service.author_identity(author)[0])
        if model:
            models.setdefault(author, Counter())[(model, effort)] += 1
```

  and in the `ProvenanceContributor(...)` add:

```python
            models=[ProvenanceModel(model=m, effort=e, beliefs=n) for (m, e), n in
                    sorted((models.get(author) or Counter()).items(), key=lambda kv: (-kv[1], kv[0][0], kv[0][1] or ""))],
```

- `episode_citations`: before the page loop, set
  `turns = turn_authorship.TurnAuthorship(memory_path, text=lambda ep: text if ep == doc_id else None)`.
  Every span on this route points into `doc_id`, whose text the function already read, so no
  second body read happens (R4B-7). Then change the span row's
  `evidence=EvidenceModel(**ev.to_dict())` to `evidence=turn_authorship.evidence_model(ev, turns)`.
  The `reasoning` row stays as is, so `EvidenceModel` stays imported.

`api/routers/episodes.py`: the `/text` ETag becomes
`extra=f"text|{episode_id}|{start}|{end}|{hash or ''}|{focus or ''}|{git_service.AUTHOR_SHAPE}",`.

`api/services/git_service.py`, the `AUTHOR_SHAPE` block:

```python
# R-B10: folded into the ETag `extra` of every read whose body carries an
# author kind (`/contributors`, `/entities/{id}/provenance`,
# `/episodes/{id}/citations`) and, since round 4 (R4B-9), a turn's model
# (`/episodes/{id}/text`, `/projects`, `/projects/{id}/timeline`). Those bodies
# change for the same commits and claims, so an ETag over the inputs alone would
# 304 the old shape — the `graph.NODE_SHAPE` rule. Bump it when the author
# buckets or the joined model fields move.
# harness-2 (round 4 C3/C4): authorModel/authorEffort, span models, contributor models.
AUTHOR_SHAPE = "harness-2"
```

`api/tests/test_agent_labels.py:72,74`: `transclusion_resolver.claim_to_model(_claim(...))` →
`transclusion_resolver.claim_to_model(_claim(...), turns=None)` (both lines).

- [ ] **Step 4: Green, the full claim/provenance neighbourhood, then regenerate the app fixture.**

Run: `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_turn_authorship_wire.py api/tests/test_agent_labels.py api/tests/test_entity_provenance.py api/tests/test_episode_text_endpoint.py api/tests/test_session_provenance_views.py api/tests/test_claims_evidence.py api/tests/test_projects_router.py api/tests/test_projects_writes.py api/tests/test_project_timeline_events.py api/tests/test_ask_evidence.py api/tests/test_timeline_participants_cap.py -q -p no:cacheprovider`
→ 0 failed.

Run: `cd <worktree> && CICADA_WRITE_APP_FIXTURE=1 api/.venv/bin/python -m pytest api/tests/test_projects_app_fixture.py -q -p no:cacheprovider`,
then without the variable → 2 passed.
- Check the diff: `git diff app/CicadaApp/Tests/fixtures/projects-demo.json | grep '^[-+] ' | grep -v -E '"(recordedTs|authorModel|authorEffort|model|effort)"' | head`.
  It must print nothing: only the new keys may appear.
- The demo's agent happenings carry `claude-code` + a session, but the demo writes no capture
  sidecar with models, so every new value there is `null`. That is expected.

- [ ] **Step 5: Commit.**

```bash
cd <worktree> && git add api/models/schemas.py api/services/turn_authorship.py api/services/transclusion_resolver.py \
  api/routers/claims.py api/routers/projects.py api/services/project_timeline.py api/services/provenance.py \
  api/routers/episodes.py api/services/git_service.py api/tests/test_turn_authorship_wire.py \
  api/tests/test_agent_labels.py app/CicadaApp/Tests/fixtures/projects-demo.json && \
git commit -F - <<'MSG'
feat(provenance): every harness write names its turn's model and effort (round 4 C3/C4, G49, G118)

The claim wire gains recordedTs, authorModel and authorEffort (joined at read,
null when no captured turn answers); every assistant span names its turn's
model; a harness contributor lists models:[{model, effort?, beliefs}];
/episodes/{id}/text gains agent and per-turn model/effort. claim_to_model
takes the request's join as a required keyword. AUTHOR_SHAPE harness-2, now
also folded into /episodes/{id}/text and both /projects ETags; the app's demo
fixture regenerated (additive keys only). Rulings R4B-8, R4B-9, R4B-15.

<attribution lines from your session's system reminder>
MSG
```

---

### Task 5: C5 — `GET /agents/setup`, a 6 s probe, and `install.md` (G76)

**Files:**
- Modify: `api/services/agent_wiring.py`, `api/routers/agents.py`, `api/models/schemas.py`
- Create: `install.md` (repo root)
- Modify (tests): `api/tests/test_agent_wiring.py` (+1 test)
- Test: `api/tests/test_agent_setup.py` (new), `api/tests/test_install_md.py` (new)

**Interfaces:**
- Produces: `GET /agents/setup?harness=<claude-code|codex|gemini-cli|cursor|claude-desktop>` →
  `{harness, kind, title, prompt?, argv?, display?, deeplink?, config?: {path, key, value}, note?}`.
  404 for an unknown harness. Engine-free, no probe, no ETag (C5).
- Produces: `agent_wiring.mcp_step`, `hook_step`, `gemini_mcp_step`, `server_spec`,
  `cursor_deeplink`, `setup_prompt`, `setup`, `PROMPT_MAX_CHARS = 1200` and
  `PROBE_TIMEOUT_S = 6.0`.
- `GET /agents/wiring`'s response is unchanged. The shared argv fixture is untouched.

- [ ] **Step 1: Failing tests.** Create `api/tests/test_agent_setup.py`:

```python
"""Round 4 D5 / C5 (G76's in-app half): `GET /agents/setup` hands the person
what to give an agent — a prompt naming exactly the commands `/agents/wiring`
would run, a Cursor install link, or a config merge the app performs. Nothing
here probes, runs a CLI or reads a harness root. Synthetic paths only."""
from __future__ import annotations

import asyncio
import base64
import json
import re
import shlex
from pathlib import Path
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import agent_wiring
from api.services.connections import base

REPO = Path("/opt/example-person/Documents/code/cicada")   # a 41-character checkout (R4B-11)
PY = f"{REPO}/api/.venv/bin/python"
MEM = REPO / "memory"
HOME = Path("/opt/example-person")
BINARIES = {"claude": "/opt/homebrew/bin/claude", "codex": "/opt/homebrew/bin/codex",
            "gemini": "/opt/homebrew/bin/gemini"}
SPEC = {"command": PY, "args": [f"{REPO}/mcp/server.py"], "env": {"CICADA_MEMORY_PATH": str(MEM)}}


def _setup(harness, *, home=HOME, resolve=BINARIES.get):
    return agent_wiring.setup(harness, home=home, memory_root=MEM, repo=REPO, python=PY, resolve=resolve)


def _runner(rc):
    async def run(argv, *, timeout):
        return base.CliResult(rc, "", "")
    return run


@pytest.mark.parametrize("harness", ["claude-code", "codex"])
def test_the_prompt_runs_exactly_what_the_wiring_would(tmp_path, harness):
    setup = _setup(harness, home=tmp_path)
    wiring = asyncio.run(agent_wiring.probe(home=tmp_path, memory_root=MEM, repo=REPO, python=PY,
                                            runner=_runner(1), resolve=BINARIES.get))
    row = next(a for a in wiring["agents"] if a["id"] == harness)
    assert setup["kind"] == "prompt"
    assert setup["argv"] == [s["argv"] for s in row["connect"]]      # C5: the same argv
    assert setup["display"] == [shlex.join(a) for a in setup["argv"]]
    numbered = [line.split(". ", 1)[1] for line in setup["prompt"].splitlines() if re.match(r"^\d+\. ", line)]
    assert numbered == setup["display"]                              # every command, verbatim, nothing else


@pytest.mark.parametrize("harness", ["claude-code", "codex", "gemini-cli"])
def test_the_prompt_is_short_plain_and_says_what_it_touches(harness):
    prompt = _setup(harness)["prompt"]
    assert len(prompt) <= agent_wiring.PROMPT_MAX_CHARS, len(prompt)
    assert "change nothing else" in prompt and "uploads nothing" in prompt


def test_gemini_gets_its_own_add_command_and_no_hook():
    assert _setup("gemini-cli")["argv"] == [[
        "/opt/homebrew/bin/gemini", "mcp", "add", "-s", "user", "-e", f"CICADA_MEMORY_PATH={MEM}",
        "cicada", PY, f"{REPO}/mcp/server.py"]]


def test_a_cli_the_backend_cannot_find_is_named_bare():
    assert _setup("claude-code", resolve=lambda name: None)["argv"][0][0] == "claude"


def test_cursor_gets_its_install_link_with_the_server_inside():
    setup = _setup("cursor")
    assert (setup["kind"], setup.get("prompt"), setup.get("argv")) == ("deeplink", None, None)
    link = setup["deeplink"]
    assert link.startswith("cursor://anysphere.cursor-deeplink/mcp/install?name=cicada&config=")
    assert json.loads(base64.b64decode(unquote(link.split("config=", 1)[1]))) == SPEC


def test_the_claude_app_gets_a_merge_the_app_performs():
    setup = _setup("claude-desktop")
    assert setup["kind"] == "config-merge"
    assert setup["config"] == {"path": "~/Library/Application Support/Claude/claude_desktop_config.json",
                               "key": "mcpServers.cicada", "value": SPEC}
    assert "Quit and reopen" in setup["note"]


def test_an_unknown_harness_has_no_setup():
    assert _setup("chatgpt") is None


def test_the_route_serves_every_harness_and_never_runs_a_cli(tmp_path, monkeypatch):
    async def boom(*a, **k):
        raise AssertionError("/agents/setup must never run a CLI")

    (tmp_path / "memory").mkdir()
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path / "memory"))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(base, "run_cli", boom)
    config.get_settings.cache_clear()
    try:
        client = TestClient(main.app)
        for harness in ("claude-code", "codex", "gemini-cli", "cursor", "claude-desktop"):
            r = client.get(f"/agents/setup?harness={harness}")
            assert r.status_code == 200, (harness, r.text)
            assert r.json()["harness"] == harness and r.json()["title"]
        assert client.get("/agents/setup?harness=nope").status_code == 404
        assert client.get("/agents/setup").status_code == 422
    finally:
        config.get_settings.cache_clear()
```

Append to `api/tests/test_agent_wiring.py` (add `import time` at the top):

```python
def test_the_probes_run_side_by_side_on_a_six_second_budget(tmp_path):
    """R4B-12: the live Welcome read Claude Code as 'couldn't check in time' at
    2 s — `claude mcp get` starts the server to health-check it."""
    assert agent_wiring.PROBE_TIMEOUT_S == 6.0

    async def slow(argv, *, timeout):
        assert timeout == 6.0
        await asyncio.sleep(0.4)
        return base.CliResult(0, "", "")

    started = time.perf_counter()
    asyncio.run(agent_wiring.probe(home=tmp_path, memory_root=MEM, repo=REPO, python=PY, runner=slow,
                                   resolve=lambda name: name))
    # Two 0.4 s probes at once (~0.4 s), never 0.8 s in a row; the margin absorbs a loaded CI box.
    assert time.perf_counter() - started < 0.7
```

Create `api/tests/test_install_md.py`:

```python
"""G76 (round 4): `install.md` is the fresh-Mac path a person pastes into an
agent — it names real commands, real Make targets, the README's clone URL and no
machine's paths."""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TEXT = (REPO / "install.md").read_text(encoding="utf-8")


def test_it_names_the_real_steps():
    for command in ("./install.sh", "make install-app", "open ~/Applications/Cicada.app",
                    "http://127.0.0.1:8000/healthz"):
        assert command in TEXT, command
    clone = re.search(r"git clone (\S+)", (REPO / "README.md").read_text(encoding="utf-8")).group(1)
    assert f"git clone {clone}" in TEXT
    targets = set(re.findall(r"^([a-z][a-z-]*):", (REPO / "Makefile").read_text(encoding="utf-8"), re.M))
    for target in re.findall(r"make ([a-z][a-z-]*)", TEXT):
        assert target in targets, target


def test_it_never_loops_the_doctor_and_names_no_machine():
    assert "/Users/" not in TEXT and "/home/" not in TEXT
    assert "in a loop" in TEXT  # the fresh-bank doctor checks fail until the first Sleep (G76 prereq)
```

Run: `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_agent_setup.py api/tests/test_agent_wiring.py api/tests/test_install_md.py -q -p no:cacheprovider` → red.

- [ ] **Step 2: Implement.**

`api/services/agent_wiring.py`:
- Docstring: change "Each CLI probe gets 2 s; … (verified 2026-09-23: `claude mcp get` health-checks
  the server, ~1.3 s when registered)" to: "Each CLI probe gets 6 s and they run side by side; a
  timeout is `unknown`, never `off`. That was 2 s until round 4 (R4B-12), when the live Welcome
  read Claude Code as 'couldn't check in time': `claude mcp get` starts the server to health-check
  it, ~1.3 s warm and longer cold."
- Add this paragraph to the docstring: "``setup`` (round 4 D5, C5; G76's in-app half) serves what
  to hand an agent instead of running anything: a prompt that names exactly the commands this
  module's step builders produce, Cursor's install link, or a config merge the app performs. No
  probe, no subprocess, no harness file read."
- Imports: add `import base64` and `from urllib.parse import quote`.
- `PROBE_TIMEOUT_S = 6.0`.
- Replace the inline step construction in `_harness` with the builders below. The two
  `connect.append(...)` lines become:

```python
    if recall == "off":
        connect.append(mcp_step(h, binary, memory_root=memory_root, repo=repo, python=python))
    if autosave in ("off", "stale"):
        connect.append(hook_step(h, home=home, repo=repo, python=python))
```

  `settings_path`/`command` stay where `_autosave` needs them.
- Add, after `_step`:

```python
def mcp_step(h: Harness, binary: str, *, memory_root: Path, repo: Path, python: str) -> dict:
    """install.sh's MCP registration — the ONE argv `/agents/wiring` offers and
    `/agents/setup` names (C5: the two can never disagree)."""
    return _step("mcp", [binary, "mcp", "add", "cicada", *h.scope, "--env", f"CICADA_MEMORY_PATH={memory_root}",
                         "--", python, str(repo / "mcp" / "server.py")], [h.config_touch])


def hook_step(h: Harness, *, home: Path, repo: Path, python: str) -> dict:
    """install.sh's G105 Stop-hook registration, merged in by `registry.py`."""
    return _step("hook", [python, str(repo / "api" / "hooks" / "registry.py"), "install",
                          "--settings", str(home / h.settings), "--event", "Stop",
                          "--command", hook_command(python, repo, h.id)], [f"~/{h.settings}"])


GEMINI_SETTINGS = ".gemini/settings.json"


def gemini_mcp_step(binary: str, *, memory_root: Path, repo: Path, python: str) -> dict:
    """`gemini mcp add [options] <name> <command> [args...]` with user scope, per
    the Gemini CLI docs (checked 2026-09-24, not run). Served only inside a
    prompt the person's own agent runs; `/agents/wiring`'s row stays read-only
    until the app has verified it (R-IA15, R4B-10)."""
    return _step("mcp", [binary, "mcp", "add", "-s", "user", "-e", f"CICADA_MEMORY_PATH={memory_root}",
                         "cicada", python, str(repo / "mcp" / "server.py")], [f"~/{GEMINI_SETTINGS}"])


def server_spec(*, memory_root: Path, repo: Path, python: str) -> dict:
    """The MCP server as a config object — the shape `ConnectView.swift` already
    writes for Cursor and the Claude app."""
    return {"command": python, "args": [str(repo / "mcp" / "server.py")],
            "env": {"CICADA_MEMORY_PATH": str(memory_root)}}


CURSOR_INSTALL = "cursor://anysphere.cursor-deeplink/mcp/install"
CLAUDE_DESKTOP_CONFIG = "~/Library/Application Support/Claude/claude_desktop_config.json"
PROMPT_MAX_CHARS = 1200
_PRODUCT = {"claude-code": "Claude Code", "codex": "Codex", "gemini-cli": "Gemini CLI"}
_NEW_SESSION = "Once it's done, start a new conversation so it can see your memory."


def cursor_deeplink(spec: dict) -> str:
    """Cursor's install link: base64 of the inner server object, percent-encoded —
    the bytes the app already builds (R4B-10), so `+`/`=` survive the query."""
    raw = json.dumps(spec, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return f"{CURSOR_INSTALL}?name=cicada&config={quote(base64.b64encode(raw).decode('ascii'), safe='')}"


def setup_prompt(product: str, steps: list[dict]) -> str:
    """What a person pastes into an agent (C5): every command verbatim and
    numbered, nothing else numbered, a request to change nothing else, and what
    it does not do. ≈ 420 characters of prose, so the commands fit the 1,200 cap
    for a checkout path up to about 60 characters — a command is never shortened
    (R4B-11)."""
    numbered = "\n".join(f"{i}. {s['display']}" for i, s in enumerate(steps, 1))
    why = ("The first lets you read and add to my memory; the second saves our conversations into Cicada "
           "after each reply." if len(steps) > 1 else "It lets you read and add to my memory.")
    return (f"Please connect Cicada, the memory app on this Mac, to {product}. Run these commands exactly as "
            f"written, one at a time, and change nothing else:\n\n{numbered}\n\n{why} If one says Cicada is "
            "already set up, that's fine. This uploads nothing: my memory stays on this computer. Then tell me "
            "in one sentence whether it worked.")


def _prompt_setup(harness: str, steps: list[dict], note: str = _NEW_SESSION) -> dict:
    return {"harness": harness, "kind": "prompt", "title": f"Connect {_PRODUCT[harness]}",
            "prompt": setup_prompt(_PRODUCT[harness], steps), "argv": [s["argv"] for s in steps],
            "display": [s["display"] for s in steps], "note": note}


def setup(harness: str, *, home: Path, memory_root: Path, repo: Path = REPO_ROOT, python: str | None = None,
          resolve=base.resolve_binary) -> dict | None:
    """`GET /agents/setup` (C5). Both steps always for Claude Code and Codex —
    the prompt tells the agent a step already done is fine — so it never needs
    a probe; the binary is the absolute path when this process can resolve it,
    else the bare name the agent's own shell resolves. None = unknown harness."""
    python = python or venv_python(repo)
    spec = server_spec(memory_root=memory_root, repo=repo, python=python)
    known = {h.id: h for h in HARNESSES}
    if harness in known:
        h = known[harness]
        binary = resolve(h.binary) or h.binary
        return _prompt_setup(harness, [mcp_step(h, binary, memory_root=memory_root, repo=repo, python=python),
                                       hook_step(h, home=home, repo=repo, python=python)])
    if harness == "gemini-cli":
        binary = resolve("gemini") or "gemini"
        return _prompt_setup(harness, [gemini_mcp_step(binary, memory_root=memory_root, repo=repo, python=python)],
                             note="Once it's done, start a new Gemini CLI session so it can see your memory. "
                                  "Gemini CLI conversations aren't saved into Cicada on their own yet.")
    if harness == "cursor":
        return {"harness": harness, "kind": "deeplink", "title": "Connect Cursor", "deeplink": cursor_deeplink(spec),
                "note": "Cursor asks you to confirm. Then open a new chat so it can see your memory."}
    if harness == "claude-desktop":
        return {"harness": harness, "kind": "config-merge", "title": "Connect the Claude app",
                "config": {"path": CLAUDE_DESKTOP_CONFIG, "key": "mcpServers.cicada", "value": spec},
                "note": "Quit and reopen Claude so it picks Cicada up."}
    return None
```

`api/models/schemas.py`, after `AgentWiringResponse`:

```python
class AgentSetupConfig(CamelModel):
    """A config merge the APP performs (round 4 D5): backup first, merge never
    replace, an unparseable file left untouched. ``path`` is ``~``-relative."""

    path: str
    key: str
    value: dict[str, Any]


class AgentSetupResponse(CamelModel):
    """``GET /agents/setup?harness=`` (round 4 C5, G76). ``kind`` says which of
    ``prompt`` / ``argv`` / ``display`` (a paste-into-your-agent prompt naming
    exactly those commands, ``display == shlex.join(argv)``), ``deeplink`` or
    ``config`` is set. ``remote`` is reserved: no harness produces it yet."""

    harness: str
    kind: Literal["prompt", "deeplink", "config-merge", "remote"]
    title: str
    prompt: Optional[str] = None
    argv: Optional[list[list[str]]] = None
    display: Optional[list[str]] = None
    deeplink: Optional[str] = None
    config: Optional[AgentSetupConfig] = None
    note: Optional[str] = None
```

`api/routers/agents.py`:
- Imports: `from fastapi import APIRouter, Depends, HTTPException, Query`, and add
  `AgentSetupResponse` to the schemas import.
- Append:

```python
@router.get("/agents/setup", response_model=AgentSetupResponse)
async def setup(harness: str = Query(..., max_length=40),
                settings: Settings = Depends(get_settings)) -> AgentSetupResponse:
    """Round 4 C5 (G76's in-app half): what to hand an agent so it connects
    itself. Engine-free and static per machine — no probe, no subprocess, no
    harness file read — so no ETag (not a Store domain)."""
    data = agent_wiring.setup(harness, home=Path.home(), memory_root=settings.memory_root)
    if data is None:
        raise HTTPException(404, f"No setup for {harness!r}")
    return AgentSetupResponse(**data)
```

  Update the module docstring: "``GET /agents/wiring`` (Track I T3) and ``GET /agents/setup``
  (round 4 C5). Request/response, not sync domains: no ETag, nothing cached."

Create `install.md` at the repo root:

```markdown
# Install Cicada

Cicada is a memory for your AI agents that lives on your Mac. The easiest way to install it is to let
an agent you already use do it for you.

## The one-paste way

Open Claude Code or Codex in a terminal and paste this:

> Install Cicada on this Mac for me. Follow https://github.com/rorosaga/cicada/blob/main/install.md step
> by step, ask me before installing any tool that's missing, and tell me when the app is open.

The agent reads the steps below and runs them, and it asks you before it installs anything new.
Nothing of yours is uploaded: Cicada keeps your memory on this computer.

## What the agent does

You can follow along, or run the steps yourself. You need a Mac with macOS 14 or later.

1. **Check the tools.**
   - `git --version`
   - `xcode-select -p` checks for Xcode's command line tools. If they are missing, ask first, then
     run `xcode-select --install`. It opens a macOS window; wait until it finishes.
   - `uv --version` checks for the Python tool Cicada uses. If it is missing, ask first, then run
     `curl -LsSf https://astral.sh/uv/install.sh | sh` and open a new shell.
2. **Get Cicada** into a folder that will stay put. The app and your agents point at this folder, so
   don't use Downloads or a temporary folder:
   `git clone https://github.com/rorosaga/cicada.git ~/cicada`
   If `~/cicada/install.sh` already exists, Cicada is already there: run `cd ~/cicada && git pull`
   instead. If `~/cicada` exists but has no `install.sh` (an older install may have put only a
   `memory` folder there), stop and ask the person what to do. Never move or delete it.
3. **Install the background service:** `cd ~/cicada && ./install.sh`
   It is safe to run again. It does five things:
   - sets up Python
   - creates the memory folder
   - starts Cicada's background service
   - registers Cicada with Claude Code
   - turns on saving each Claude Code (and Codex) conversation into Cicada

   When an agent runs it, it never asks for or prints an API key. If you want to use a key, add it
   later in the app.
4. **Build and open the app:** `cd ~/cicada && make install-app && open ~/Applications/Cicada.app`
   The first build takes a few minutes.
5. **Check it's running:** `curl -s http://127.0.0.1:8000/healthz` should answer.
6. **Hand over.** Tell the person the app is open. Its Welcome screen takes it from there: connecting
   other agents, importing chat exports and turning on calendars.

## Rules for the agent

- Change nothing outside `~/cicada` except what `./install.sh` itself does.
- Never type, paste or print an API key or a password.
- If a step fails, stop. Show the person the last lines of the error and say in plain words what
  went wrong.
- `make doctor` is a fuller health check. On a brand-new memory, two of its checks only pass after
  Cicada's first read of your conversations, so don't retry it in a loop.

## Updating later

`cd ~/cicada && git pull && ./install.sh && make install-app`
```

- [ ] **Step 3: Green.**

Run: `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_agent_setup.py api/tests/test_agent_wiring.py api/tests/test_install_md.py -q -p no:cacheprovider` → 0 failed.
`test_the_shared_argv_fixture_matches` and `test_no_author_machine_path_is_baked_in` must stay green.

- [ ] **Step 4: Commit.**

```bash
cd <worktree> && git add api/services/agent_wiring.py api/routers/agents.py api/models/schemas.py install.md \
  api/tests/test_agent_setup.py api/tests/test_agent_wiring.py api/tests/test_install_md.py && \
git commit -F - <<'MSG'
feat(agents): /agents/setup — connect an agent by pasting one prompt; install.md (round 4 D5, C5, G76)

GET /agents/setup?harness= serves a plain prompt naming exactly the commands
/agents/wiring would run (one set of step builders, display == shlex.join(argv))
for Claude Code, Codex and Gemini CLI; Cursor's install link; and a Claude-app
config merge the app performs. No probe, no subprocess. The wiring probe budget
goes 2 s → 6 s (the live Welcome timed out), still side by side. install.md is
the fresh-Mac paste-into-your-agent path. Rulings R4B-10..12, R4B-14.

<attribution lines from your session's system reminder>
MSG
```

---

### Task 6: C6 — `POST /sources/calendar-local/sync` and the `calendar-local` channel (G142)

**Files:**
- Create: `api/services/calendar_local.py`
- Modify: `api/routers/local_sources.py`, `api/models/schemas.py`, `api/services/channel_registry.py`,
  `api/services/source_overview.py`
- Modify (tests): `api/tests/test_demo_capture_routes.py` (`GATED`), `api/tests/test_source_channels.py:259-262,333-336`,
  `api/tests/test_folder_source.py:230-233` (`APP_SYNC_ROUTED`)
- Test: `api/tests/test_calendar_local.py` (new)

**Interfaces:**
- Produces: `POST /sources/calendar-local/sync`. The body is `{window: {from, to}, calendars:
  [{id, title, account?}], events: [{id, calendarId, title, start, end, allDay, location?, notes?,
  url?, attendees?, organizer?, lastModified?}]}`, and it returns `{created, updated, unchanged,
  tombstoned, bank}` (C6).
- Status codes: 409 into a demo bank, 413 above 5,000 events, 422 for a bad window.
- Produces: `calendar_local.CHANNEL_ID = "calendar-local"`, `LABEL = "Apple Calendar"`,
  `MAX_EVENTS`, `NOTES_CAP` and `sync(memory_path, payload, *, bank)`.
- Produces: a `calendar-local` row on `GET /sources/channels`, and a `CATALOG` row.

- [ ] **Step 1: Failing tests.** Create `api/tests/test_calendar_local.py`:

```python
"""G142 (round 4 D2, C6): Apple Calendar through EventKit — the backend half.
The app posts a rolling window; each event is one episode through the G20
stager, scrubbed, edited in place, tombstoned when it vanishes, committed once
per sync as the person. Synthetic events on example.com only."""
from __future__ import annotations

import subprocess

import pytest
from fastapi.testclient import TestClient

from _synthetic_bank import _bank
from api import config, main
from api.services import bank_index, calendar_local, demo_guard, markdown_parser, source_overview

WORK = {"id": "cal-work", "title": "Work", "account": "example.com"}
HOME = {"id": "cal-home", "title": "Home"}
WINDOW = {"from": "2026-09-01T00:00:00+00:00", "to": "2026-10-01T00:00:00+00:00"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    yield TestClient(main.app), memory
    config.get_settings.cache_clear()


def _event(eid, title="Alpha review", start="2026-09-24T10:00:00+02:00", cal="cal-work", **kw):
    return {"id": eid, "calendarId": cal, "title": title, "start": start, "end": "2026-09-24T11:00:00+02:00",
            "allDay": False, **kw}


def _post(c, events, calendars=(WORK, HOME), window=WINDOW):
    return c.post("/sources/calendar-local/sync",
                  json={"window": window, "calendars": list(calendars), "events": events})


def _episodes(memory):
    out = {}
    for path in sorted((memory / "episodes").glob("*.md")):
        parsed = markdown_parser.parse(path)
        sid = str(parsed.frontmatter.get("source_id") or "")
        if sid.startswith("calendar-local:"):
            out[sid] = parsed
    return out


def _head(memory):
    return subprocess.run(["git", "-C", str(memory), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True).stdout.strip()


def test_a_first_sync_stages_one_episode_per_event_and_commits_once_as_the_person(client):
    c, memory = client
    r = _post(c, [_event("E1|2026-09-24T08:00:00Z", attendees=["bob-example", "carol-example"],
                         organizer="bob-example", location="Room 4")])
    assert r.status_code == 200, r.text
    assert r.json() == {"created": 1, "updated": 0, "unchanged": 0, "tombstoned": 0, "bank": memory.name}
    [(sid, ep)] = _episodes(memory).items()
    assert sid == "calendar-local:E1|2026-09-24T08:00:00Z"
    fm = ep.frontmatter
    assert (fm["origin"], fm["source"], fm["processed"], fm["calendar_id"]) == (
        "calendar-local", "calendar-local", False, "cal-work")
    assert fm["event_start"] == "2026-09-24T10:00:00+02:00"
    assert ep.body.startswith("# Alpha review\n\n**Start:** 2026-09-24T10:00:00+02:00")
    assert "**Calendar:** Work (example.com)" in ep.body
    assert "**Attendees:** bob-example, carol-example" in ep.body and "**Location:** Room 4" in ep.body
    log = subprocess.run(["git", "-C", str(memory), "log", "-1", "--format=%B"], capture_output=True, text=True,
                         check=True).stdout
    assert log.startswith("Calendar sync") and "capture/calendar" in log and "Cicada-Author: user" in log


def test_the_same_window_again_changes_nothing_and_commits_nothing(client):
    c, memory = client
    _post(c, [_event("E1")])
    before = _head(memory)
    assert _post(c, [_event("E1")]).json()["unchanged"] == 1
    assert _head(memory) == before


def test_an_edit_rewrites_in_place_and_requeues(client):
    c, memory = client
    _post(c, [_event("E1")])
    [before] = _episodes(memory).values()
    assert _post(c, [_event("E1", title="Alpha review (moved)")]).json()["updated"] == 1
    [after] = _episodes(memory).values()
    assert after.frontmatter["id"] == before.frontmatter["id"] and after.frontmatter["processed"] is False
    assert after.body.startswith("# Alpha review (moved)")


def test_only_an_event_gone_from_a_named_calendar_inside_the_window_is_tombstoned(client):
    c, memory = client
    _post(c, [_event("E1"), _event("E2", start="2026-09-25T10:00:00+02:00"),
              _event("E3", cal="cal-elsewhere"), _event("E4", start="2026-12-24T10:00:00+01:00")],
          calendars=(WORK, HOME, {"id": "cal-elsewhere", "title": "Elsewhere"}))
    r = _post(c, [], calendars=(WORK, HOME))
    assert r.json()["tombstoned"] == 2
    eps = _episodes(memory)
    assert len(eps) == 4, "a tombstone keeps the file"
    gone = {sid for sid, ep in eps.items() if ep.frontmatter.get("source_deleted_at")}
    assert gone == {"calendar-local:E1", "calendar-local:E2"}
    assert _post(c, [_event("E1")], calendars=(WORK, HOME)).json()["updated"] == 1   # it came back (R-F1)
    assert not _episodes(memory)["calendar-local:E1"].frontmatter.get("source_deleted_at")


def test_notes_are_scrubbed_before_they_are_cut_and_a_link_loses_its_query(client):
    c, memory = client
    secret = "sk-" + "Z" * 24
    # Words, not one long run: a 1,990-character run of one letter is itself scrubbed as a
    # base64-like run, which would hide the ordering this test is about. Checked: cutting
    # first leaves "sk-ZZZZZZ" behind; scrubbing first leaves nothing.
    notes = "note " * 398 + secret + " tail"
    _post(c, [_event("E1", notes=notes, url="https://meet.example.com/j/123?pwd=abc123#frag",
                     attendees=[f"guest-{i}@example.com" for i in range(60)])])
    body = next(iter(_episodes(memory).values())).body
    assert "sk-" not in body, "a secret straddling the cut is redacted whole (R4B-13)"
    assert len(body.split("## Notes\n", 1)[1]) <= calendar_local.NOTES_CAP
    assert "**Link:** https://meet.example.com/j/123\n" in body and "pwd" not in body
    assert "(+10 more)" in body and "guest-59@" not in body


@pytest.mark.parametrize("window", [
    {"from": "2026-09-01T00:00:00", "to": "2026-10-01T00:00:00+00:00"},       # no offset
    {"from": "2026-10-01T00:00:00+00:00", "to": "2026-09-01T00:00:00+00:00"},  # out of order
])
def test_a_window_the_backend_cannot_trust_is_refused(client, window):
    c, memory = client
    assert _post(c, [_event("E1")], window=window).status_code == 422
    assert _episodes(memory) == {}


def test_too_many_events_is_refused(client, monkeypatch):
    c, memory = client
    monkeypatch.setattr(calendar_local, "MAX_EVENTS", 2)
    assert _post(c, [_event("E1"), _event("E2"), _event("E3")]).status_code == 413
    assert _episodes(memory) == {}


def test_a_demo_bank_is_refused_and_nothing_is_written(client, monkeypatch):
    c, memory = client
    monkeypatch.setattr(demo_guard, "is_demo", lambda path: True)
    assert _post(c, [_event("E1")]).status_code == 409
    assert _episodes(memory) == {}


def test_the_channel_is_offered_before_the_first_sync_and_counts_after(client):
    c, _ = client

    def row():
        return next(ch for ch in c.get("/sources/channels").json()["channels"] if ch["id"] == "calendar-local")

    assert (row()["label"], row()["connected"], row()["actions"]) == ("Apple Calendar", False, ["sync", "manage"])
    _post(c, [_event("E1"), _event("E2")])
    assert (row()["connected"], row()["count"], row()["countNoun"]) == (True, 2, "event")
    assert "calendar-local" in {spec.id for spec in source_overview.CATALOG}
```

Edit `api/tests/test_demo_capture_routes.py` `GATED`. After the
`("POST", "/sources/folders/{folder_id}/sync")` entry add:

```python
    ("POST", "/sources/calendar-local/sync"): "/sources/calendar-local/sync",
```

Edit `api/tests/test_source_channels.py`: in both pinned id lists (`:259-262` and `:333-336`),
append `"calendar-local"` after `"files"`.

Edit `api/tests/test_folder_source.py` `APP_SYNC_ROUTED` (`:230-233`). The new row carries `sync`,
so `test_every_sync_row_the_registry_can_emit_is_one_the_app_routes` must list it. Add
`"calendar-local"` to the set, and extend the comment above it with one line: "round 4 (G142):
`calendar-local` — the app's EventKit reader (feat/r4-foundations-app) owns its `syncRoute`."

Run: `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_calendar_local.py api/tests/test_demo_capture_routes.py api/tests/test_source_channels.py api/tests/test_folder_source.py -q -p no:cacheprovider` → red.

- [ ] **Step 2: Implement.** Create `api/services/calendar_local.py`:

```python
"""Apple Calendar through EventKit — the backend half (G142; round 4 D2, contract C6).

ICS subscriptions (`calendar_registry`) reach only calendars that publish a
link. The Mac's Calendar app holds every account, so the APP reads it through
EventKit after one standard permission prompt and posts a rolling window here —
the backend never opens `~/Library` (the Awake rail). Each event becomes one
episode through the G20 stager keyed `calendar-local:<id>` (`id` = the external
identifier, plus the occurrence start for a recurring event): an edit rewrites
it in place and re-queues it, an event gone from the window is tombstoned and
kept (R-F1), and every body is scrubbed before it is hashed (R-N3).

What an event may carry into the bank, and why (R4B-13):
* notes — scrubbed FIRST, then cut at 2,000 characters, so a passcode that
  straddles the cut is redacted whole instead of half-kept;
* a link — scheme, host and path only: a meeting URL's passcode lives in its
  query (`?pwd=`), and the bank needs the place, not the key;
* attendees — the first 50 names, then "(+N more)";
* title, location, organizer, calendar — 300 characters each; the title is
  scrubbed too, because it also lands in frontmatter the stager does not scrub.

One request carries the whole window: a tombstone needs the complete set, so an
event is tombstoned only when its calendar is named in the request, its stored
start lies in [from, to) and it was not posted — a calendar the request does not
name says nothing about its events. The episode is dated the day Cicada learned
of the event (the ICS path's rule); the event's own times are in the body, where
Sleep reads dates, and in `event_start`/`event_end`.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from api.services import episode_scrub, episode_staging

CHANNEL_ID = "calendar-local"
LABEL = "Apple Calendar"
ORIGIN = CHANNEL_ID
#: The scrub ledger's writer word (`episode_scrub.WRITERS` is a closed enum and
#: already has `calendar`, the ICS path's): an unlisted `calendar-local` would
#: be recorded as `other` (R4B-13).
SCRUB_WRITER = "calendar"
SOURCE_PREFIX = f"{CHANNEL_ID}:"
MAX_EVENTS = 5000
NOTES_CAP = 2000
TEXT_CAP = 300
URL_CAP = 2000
ATTENDEES_SHOWN = 50


class PayloadError(ValueError):
    """A request the backend cannot trust — answered 422, nothing staged."""


def instant(value) -> datetime | None:
    """An aware instant, or None. A bare date is that day's UTC midnight (an
    all-day event); a naive time is refused — a window with no offset could
    tombstone the wrong day's events."""
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else None
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=timezone.utc)
    text = str(value or "").strip()
    if len(text) == 10:
        try:
            return datetime.combine(date.fromisoformat(text), time.min, tzinfo=timezone.utc)
        except ValueError:
            return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _clip(value, cap: int = TEXT_CAP) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= cap else text[: cap - 1].rstrip() + "…"


def _link(value) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parts = urlsplit(raw)
        host = parts.hostname or ""
        port = f":{parts.port}" if parts.port else ""
    except ValueError:
        return None
    if not parts.scheme or not host:
        return None
    return urlunsplit((parts.scheme, host + port, parts.path, "", ""))[:URL_CAP]


def _notes(value) -> tuple[str | None, int]:
    text, n = episode_scrub.scrub(str(value or ""))
    text = text.strip()
    if not text:
        return None, n
    if len(text) > NOTES_CAP:
        text = text[: NOTES_CAP - 1].rstrip() + "…"
    return text, n


def body_for(event: dict, calendar: dict | None) -> tuple[str, int]:
    """The ICS path's episode shape (`calendar_registry._episode_body`), plus the
    fields EventKit gives: organizer, attendees, a link. Returns the body and how
    many notes replacements the scrub made (for the ledger)."""
    lines = [f"# {_clip(event.get('title')) or 'Untitled event'}", "",
             f"**Start:** {event.get('start')}" + (" (all-day)" if event.get("all_day") else "")]
    if event.get("end"):
        lines.append(f"**End:** {event['end']}")
    if location := _clip(event.get("location")):
        lines.append(f"**Location:** {location}")
    if calendar and (name := _clip(calendar.get("title"))):
        account = _clip(calendar.get("account"))
        lines.append(f"**Calendar:** {name}" + (f" ({account})" if account else ""))
    if organizer := _clip(event.get("organizer")):
        lines.append(f"**Organizer:** {organizer}")
    people = [p for p in (_clip(a) for a in (event.get("attendees") or [])) if p]
    if people:
        more = len(people) - ATTENDEES_SHOWN
        lines.append("**Attendees:** " + ", ".join(people[:ATTENDEES_SHOWN]) + (f" (+{more} more)" if more > 0 else ""))
    if link := _link(event.get("url")):
        lines.append(f"**Link:** {link}")
    notes, scrubbed = _notes(event.get("notes"))
    if notes:
        lines += ["", "## Notes", notes]
    return "\n".join(lines), scrubbed


def _vanished(sid: str, fm: dict, posted: dict, calendars: dict, start: datetime, end: datetime) -> bool:
    if not sid.startswith(SOURCE_PREFIX) or sid in posted or fm.get("source_deleted_at"):
        return False
    if str(fm.get("calendar_id") or "") not in calendars:
        return False      # a calendar this request does not name says nothing about its events
    at = instant(fm.get("event_start"))
    return at is not None and start <= at < end


def sync(memory_path: Path, payload: dict, *, bank: str | None = None) -> dict:
    """Stage one window (C6). `payload` is the request with snake_case keys
    (`window.start`/`window.end` are the wire's `from`/`to`). Returns the four
    counts, the live event count for the channel row, and the bank-relative
    paths to commit."""
    window = payload.get("window") or {}
    start, end = instant(window.get("start")), instant(window.get("end"))
    if start is None or end is None:
        raise PayloadError("window.from and window.to must be times with a UTC offset")
    if start >= end:
        raise PayloadError("window.from must be before window.to")
    calendars = {str(c.get("id")): c for c in (payload.get("calendars") or []) if c.get("id")}
    events: dict[str, dict] = {}
    for ev in payload.get("events") or []:
        if ev.get("id"):
            events[SOURCE_PREFIX + str(ev["id"])] = ev      # a repeated id: the last one wins
    if len(events) > MAX_EVENTS:
        raise PayloadError(f"at most {MAX_EVENTS} events per sync")
    drafts: list[episode_staging.EpisodeDraft] = []
    scrubbed = 0
    for sid, ev in events.items():
        body, n = body_for(ev, calendars.get(str(ev.get("calendar_id") or "")))
        title, m = episode_scrub.scrub(_clip(ev.get("title")) or "Untitled event")
        scrubbed += n + m
        extra = {"event_start": str(ev.get("start") or ""), "calendar_id": str(ev.get("calendar_id") or "")}
        if ev.get("end"):
            extra["event_end"] = str(ev["end"])
        drafts.append(episode_staging.EpisodeDraft(
            title=title, source_id=sid, source_updated_at=str(ev.get("last_modified") or "") or None,
            source=ORIGIN, origin=ORIGIN, body=body, extra=extra, writer=SCRUB_WRITER))
    episodes_dir = Path(memory_path) / "episodes"
    episodes_dir.mkdir(parents=True, exist_ok=True)
    with episode_staging.STAGE_LOCK:
        index, _ = episode_staging.scan(episodes_dir)
        gone = sorted(sid for sid, entry in index.items()
                      if _vanished(sid, entry.fm, events, calendars, start, end))
        result = episode_staging.stage(drafts, episodes_dir, deleted_source_ids=gone, bank=bank)
    # The notes and the frontmatter title were scrubbed here, before the stager
    # saw them; the stager records its own body pass under the same writer.
    episode_scrub.record(SCRUB_WRITER, scrubbed, bank=bank)
    return {"created": result.created, "updated": result.updated, "unchanged": result.skipped,
            "tombstoned": result.tombstoned, "live": len(events), "paths": list(result.paths)}
```

`api/models/schemas.py`, after `WisprFlowCaptureResponse`:

```python
class CalendarLocalWindow(CamelModel):
    """``from``/``to`` on the wire (round 4 C6); ``start``/``end`` in Python,
    where ``from`` is a keyword. Aware ISO-8601 times."""

    start: str = Field(alias="from")
    end: str = Field(alias="to")


class CalendarLocalCalendar(CamelModel):
    id: str
    title: str = ""
    account: Optional[str] = None


class CalendarLocalEvent(CamelModel):
    """One EventKit event (C6). ``id`` = ``calendarItemExternalIdentifier``, plus
    ``|`` and the occurrence start for a recurring event."""

    id: str
    calendar_id: str = ""
    title: str = ""
    start: str
    end: Optional[str] = None
    all_day: bool = False
    location: Optional[str] = None
    notes: Optional[str] = None
    url: Optional[str] = None
    attendees: list[str] = []
    organizer: Optional[str] = None
    last_modified: Optional[str] = None


class CalendarLocalSyncRequest(CamelModel):
    """``POST /sources/calendar-local/sync`` (G142). One request carries the
    WHOLE window — a tombstone needs the complete set (R4B-13)."""

    window: CalendarLocalWindow
    calendars: list[CalendarLocalCalendar] = []
    events: list[CalendarLocalEvent] = []


class CalendarLocalSyncResponse(CamelModel):
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    tombstoned: int = 0
    bank: str = ""
```

`api/routers/local_sources.py`:
- Add `CalendarLocalSyncRequest, CalendarLocalSyncResponse` to the schemas import, and
  `calendar_local` to the services import.
- Add to the module docstring: "Apple Calendar (G142): EventKit is read by the app; the window's
  events are posted here."
- Append:

```python
@router.post("/sources/calendar-local/sync", response_model=CalendarLocalSyncResponse, dependencies=_DEMO_GATE)
async def sync_calendar_local(req: CalendarLocalSyncRequest, settings: Settings = Depends(get_settings)):
    """G142 (round 4 C6): stage one rolling window the app read through EventKit.
    413 above ``calendar_local.MAX_EVENTS``; 422 for a window with no offset or
    out of order; nothing staged either way. One ``user`` commit per sync
    (trigger ``capture/calendar``), scoped to the episodes it wrote — a
    no-change re-read commits nothing."""
    memory_path = settings.memory_path
    if len(req.events) > calendar_local.MAX_EVENTS:
        raise HTTPException(413, f"at most {calendar_local.MAX_EVENTS} events per sync — send a shorter window")
    try:
        out = await run_in_threadpool(calendar_local.sync, memory_path, req.model_dump(by_alias=False),
                                      bank=memory_path.name)
    except calendar_local.PayloadError as exc:
        raise HTTPException(422, str(exc))
    sync_state.record_sync(memory_path, calendar_local.CHANNEL_ID, count=out.pop("live"))
    await folder_source.commit_paths_for(memory_path, out.pop("paths"), subject="Calendar sync",
                                         trigger="capture/calendar", channel=calendar_local.CHANNEL_ID)
    return CalendarLocalSyncResponse(**out, bank=memory_path.name)
```

`api/services/channel_registry.py`:
- Add `calendar_local,` to the services import.
- Add to the module docstring's list:
  "* ``calendar-local`` -> Apple Calendar through EventKit (G142), always listed, appended after
  the fixed ids".
- In `build_channels`, directly after `rows = [channels[cid] for cid in CHANNEL_IDS]`:

```python
    # G142 (round 4 D2, C6): Apple Calendar through EventKit — a standing
    # connection the APP reads and posts, so `_local_channel`'s shape. Always
    # listed, so Settings → Integrations and the Welcome can offer it before the
    # first sync; appended after the fixed ids like every local source (R-LS25:
    # the fixed list and its mirrors stay what they are).
    rows.append(_local_channel(calendar_local.CHANNEL_ID, calendar_local.LABEL, state, "event"))
```

`api/services/source_overview.py`: in `CATALOG`, directly after the ICS
`SourceSpec("calendar", …)` row:

```python
    # G142 (round 4): Apple Calendar through EventKit, so its episodes never read as a raw id.
    SourceSpec("calendar-local", "Apple Calendar", "feed", "calendar-local", ("calendar-local",), "calendar-local"),
```

- [ ] **Step 3: Green.**

Run: `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_calendar_local.py api/tests/test_demo_capture_routes.py api/tests/test_source_channels.py api/tests/test_folder_source.py api/tests/test_wispr_flow.py api/tests/test_channel_detail_numbers.py api/tests/test_source_overview.py api/tests/test_episode_writers_scrub.py api/tests/test_episode_staging.py api/tests/test_calendar_registry.py -q -p no:cacheprovider`
→ 0 failed.

- [ ] **Step 4: Commit.**

```bash
cd <worktree> && git add api/services/calendar_local.py api/routers/local_sources.py api/models/schemas.py \
  api/services/channel_registry.py api/services/source_overview.py api/tests/test_calendar_local.py \
  api/tests/test_demo_capture_routes.py api/tests/test_source_channels.py api/tests/test_folder_source.py && \
git commit -F - <<'MSG'
feat(sources): Apple Calendar through EventKit — POST /sources/calendar-local/sync (round 4 D2, C6, G142)

The app reads every calendar on the Mac and posts a rolling window; each event
is one episode through the G20 stager keyed calendar-local:<id> — edits
rewritten in place, vanished events tombstoned for the calendars the request
names, notes scrubbed then capped at 2,000, links without their query. 409 into
a demo bank; one user commit per sync (capture/calendar). /sources/channels
always lists calendar-local ("Apple Calendar"), and with a sync action, so
APP_SYNC_ROUTED gains it; the Sources catalog has its row. Ruling R4B-13.

<attribution lines from your session's system reminder>
MSG
```

---

### Task 7: Docs — CLAUDE.md, the G49 ruling, G49/G76 rows and the new G142 row

**Files:**
- Modify: `CLAUDE.md`, `docs/goals/TODO.md`, `docs/goals/memory-evolution.md`
- Stage with it: this plan (`docs/superpowers/plans/2026-09-24-r4-foundations-back.md`)

Privacy rule: no personal data. Model ids and effort words are not personal. Examples use
placeholders.

- [ ] **Step 1: `CLAUDE.md`.** Make ten edits, each by the anchor quoted. Re-read each paragraph
  first, and keep the surrounding wording.

1. **Awake → the Stop-hook rail bullet** ("Capture must not depend on a model deciding…"). After
   "tool calls, thinking, file dumps and harness-injected text are skipped by construction."
   insert:
   "From a kept agent turn it reads two more facts and nothing else (round 4 C1, G49 lifted for
   harness writes): the model id (Claude Code's `message.model`, Codex's
   `turn_context.payload.model`) and the reasoning effort (Claude Code's top-level `effort`,
   Codex's `turn_context.payload.effort`, and for the last reply the Stop hook's stdin
   `effort.level`). Both are cleaned by `agent_turns` (an effort is one of
   `minimal|low|medium|high|xhigh|max`, and anything else is dropped). They ride the sidecar on
   agent entries only; the transcript wins over the hook."
2. **"Every writer scrubs…" bullet.** `turns: [{offset, ts, speaker}, …]` →
   `turns: [{offset, ts, speaker, model?, effort?}, …]`. After "(R-PB4: … capped head-stable at
   500)" add "; `model`/`effort` only on an agent turn (round 4 C1)".
3. **"A local source is read by the app…" bullet**, at its end:
   "Apple Calendar (G142): the app reads EventKit after the one standard permission prompt and
   posts a rolling window to `POST /sources/calendar-local/sync` (one request = the whole window).
   `calendar_local.py` stages each event keyed `calendar-local:<id>`:
   - notes are scrubbed, then cut at 2,000 characters;
   - a link keeps no query;
   - an event gone from the window is tombstoned, only for the calendars the request named;
   - one `user` commit per sync (`capture/calendar`)."
4. **Conversation identity (G48).** Replace the sentence from "A conversation row's `model`" to
   "can't answer." with:
   "A conversation row's `model` stays null. The model lives per turn instead (round 4, G49's
   reservation lifted for harness writes, TODO ruling 11):
   - the Stop-hook episode's `turns` sidecar records each agent turn's `model`/`effort`;
   - a claim written through the MCP seam carries `recorded_ts`;
   - `turn_authorship.py` joins the two at read (`authorModel`/`authorEffort`), never guessed and
     never self-reported.

   An app with no capture hook (the Claude app, ChatGPT, Cursor, a remote connector) has no turn
   to join, and neither does a Codex MCP write, because Codex gives an MCP server no session id.
   The app then says the model wasn't shared."
5. **Reading provenance back (G118 slice 2, server half)**, at the paragraph's end:
   "Round 4 (C2–C4):
   - Every claim on the wire also carries `recordedTs` (stored on MCP writes only), and
     `authorModel`/`authorEffort` for a harness write. These are joined by
     `turn_authorship.TurnAuthorship`: the claim's session → its capture episode → the last
     person's turn at or before `recorded_ts` → the agent turn that answered it, with both sides
     floored to the second.
   - An `assistant` span carries its turn's `model`/`effort`.
   - A harness contributor lists `models: [{model, effort?, beliefs}]`.
   - `/episodes/{id}/text` carries `agent` (the most recent agent turn's, null when that turn
     names neither) and per-turn `model`/`effort`.
   - `claim_to_model(claim, *, turns)` takes the request's join as a required keyword.
   - `AUTHOR_SHAPE` also rides `/episodes/{id}/text` and both `/projects` ETags."
6. **Git → `Cicada-Author:` bullet.** "(G135; G49 keeps the model reserved)" →
   "(G135; the trailer never names a model — since round 4 it is joined at read from the captured
   turn)".
7. **Triggers list.** Add `capture/calendar` after `sleep/followup`.
8. **Agent wiring (Track I T3/T7).**
   - Change "2 s each, a timeout is `unknown`" to "6 s each and side by side (round 4: at 2 s the
     live Welcome read Claude Code as 'couldn't check in time'), a timeout is `unknown`".
   - Append: "`GET /agents/setup?harness=` (round 4 C5, G76's in-app half) serves what to hand an
     agent instead of running anything:
     - for Claude Code, Codex and Gemini CLI, a plain prompt (≤ 1,200 characters) that names the
       exact commands, built by the same step builders `/agents/wiring` uses (both steps always,
       `display == shlex.join(argv)`);
     - for Cursor, its install link;
     - for the Claude app, a config merge the APP performs.

     No probe, no subprocess, no ETag."
9. **API Design → the `**ETags.**` paragraph** (the one that describes `/projects`).
   - Change "`extra` = `projects|<shape>|<machine zone>`" to
     "`extra` = `projects|<shape>|<author shape>|<machine zone>` (`git_service.AUTHOR_SHAPE` since
     round 4, R4B-9)".
   - After "(no `VersionVector` mapping, fetched on demand like provenance)." add:
     "A timeline item carries at most 12 participants plus `participantsTotal`, and a cluster
     group at most 8 names no page holds yet (round 4 D6; `PROJECT_SHAPE` g141-3)."
10. **Installation & Setup.** After "`install.sh` is the source of truth;" continue:
   "`install.md` is the paste-into-your-agent path for a fresh Mac (clone → `./install.sh` →
   `make install-app` → open the app; G76), and it never loops `make doctor`."

- [ ] **Step 2: `docs/goals/TODO.md`.** Append ruling 11 after ruling 10 in "Rulings that cost
  real work to derive":

```markdown
11. **An agent's model and reasoning effort are recorded per turn — G49's reservation is lifted
    for harness writes (owner, 2026-09-24).** The owner asked that every memory write an agent
    makes be traceable to its harness, model and reasoning effort.

    Checked on a live transcript before building:
    - Claude Code's assistant lines carry `message.model` and a top-level `effort`.
    - The Stop hook's stdin carries `effort.level`.
    - Codex rollouts carry `turn_context.payload.model` and `.effort`.

    So the capture path (G105's one permitted transcript read) keeps exactly those keys on agent
    turns, and nothing else of the line: no thinking or reasoning text. A write through MCP is
    joined AT READ, by its session id and `recorded_ts`, to the turn it happened in
    (`turn_authorship.py`). It is never self-reported: an agent asked for its model can only
    guess, and a guess in provenance is worse than a blank. `Cicada-Author:` stays the harness
    label.

    Revisit when one of these happens:
    - A harness starts telling MCP servers its own model. Prefer that; it needs no join.
    - The transcript keys move. The extractor then reads null, never a wrong value.
    - A claim is ever shown with a model its turn did not use. The second-precision join rule is
      then wrong; read `turn_authorship.turn_at` first.
```

- [ ] **Step 3: `docs/goals/memory-evolution.md`.** Every row of this table is ONE physical line
  with no `<br>` (check with `sed -n '/^| G76 /p'`). A newline or a Markdown list inside a
  cell ends the row and breaks the table. So each append below is a single line of text, pasted
  in just before the ` | <status> |` that closes the row. The sentences are separated by spaces,
  and the list items use `(1) … (2) …`.
  - **G49 row:** append this single line to the end of the body cell:

```text
 **Round 4 (2026-09-24) — the model reservation is lifted for harness writes (owner; TODO ruling 11).** (1) The Stop-hook capture keeps each agent turn's `model`/`effort` in the episode's `turns` sidecar — only `message.model` + the top-level `effort` for Claude Code, `turn_context.payload.model`/`.effort` for Codex, and the hook's `effort.level` for the last reply. (2) Every MCP write, stdio and remote, carries `recorded_ts`. (3) `turn_authorship.py` joins them at read: `authorModel`/`authorEffort` on the claim wire, a model on each assistant span, `models` on a harness contributor, and `agent` plus per-turn models on `/episodes/{id}/text`. (4) `Cicada-Author:` is unchanged. **Known limits:** Codex gives an MCP server no session id, so a Codex MCP write joins to nothing even though its captured turns carry models; the same holds for an app with no hook (the Claude app, ChatGPT, Cursor, a remote connector). No backfill: an episode captured before round 4 gains models only when its session grows again.
```

    Its status cell stays as it is. The row's subscription-engine ladder is still open.
  - **G76 row:** append this single line to the end of the body cell:

```text
 **In-app half shipped (round 4, 2026-09-24):** (1) `GET /agents/setup?harness=` serves a paste-into-your-agent prompt for Claude Code, Codex and Gemini CLI, built from the same step builders `/agents/wiring` uses, and a test holds the argv equal. (2) It also serves Cursor's install link and a Claude-app config merge that the app performs. (3) The repo-root `install.md` is the fresh-Mac path. Still open: doctor's two fresh-bank checks (`leann/*.meta.json`, `_index.md`), so `install.md` says not to loop `make doctor`; and copying both skills via `--skill`.
```

    Set its status cell (currently `🔲`) to `🟡 in-app half + install.md (round 4)`.
  - **New G142 row**, directly after the G141 row:

```markdown
| G142 | **Apple Calendar through EventKit — every calendar on the Mac, not only the ones with an ICS link** (Rodrigo 2026-09-24, round 4 brief: "turn on whatever already works including calendars") | **The gap.** Calendars reached Cicada only as ICS subscriptions (`calendar_registry.py`). A calendar with no published ICS link never arrived, and even a published one needed its URL found and pasted per calendar. The Mac's Calendar app already holds every account. **The design (round 4 D2, contract C6).** The app reads EventKit after one standard macOS prompt: every account, a rolling window, re-read on `EKEventStoreChanged`. The backend never opens `~/Library` (the Awake rail). The app posts the WHOLE window to `POST /sources/calendar-local/sync`. `calendar_local.py` stages each event through `episode_staging` keyed `calendar-local:<id>` (the external identifier, plus the occurrence start for a recurring event), so an edit rewrites its episode in place and re-queues it. An event gone from the window is tombstoned (`source_deleted_at`), never deleted, but only for a calendar the request named. Notes are scrubbed first and then cut at 2,000 characters, so a passcode straddling the cut is redacted whole. A link keeps scheme, host and path only (a meeting passcode lives in the query). Attendees stop at 50. A demo bank gets 409. Each sync makes one `user` commit (`capture/calendar`), scoped to the episodes it wrote. `GET /sources/channels` always lists `calendar-local` ("Apple Calendar"), and the Sources catalog has its row. ICS subscriptions are unchanged. **Open:** a recurring event is one episode per occurrence in the window, so watch the episode count after the owner's first sync; attendees stay names in text, and Sleep's promotion rules decide whether one becomes a person page. | 🛠️ backend built (feat/r4-foundations-back); the EventKit reader ships on feat/r4-foundations-app |
```

- [ ] **Step 4: Verify the docs.**

Run: `cd <worktree> && grep -n "G142" docs/goals/memory-evolution.md | cut -c1-80 && grep -c "^11\. \*\*An agent's model" docs/goals/TODO.md && git diff --stat`.

Check the table survived: `cd <worktree> && git show HEAD:docs/goals/memory-evolution.md | grep -c '^| G'`
and `grep -c '^| G' docs/goals/memory-evolution.md` must differ by exactly 1 (the new G142 row).
Also `git diff -U0 docs/goals/memory-evolution.md | grep -c '^+'` must be 4: the `+++` header and
the three changed or added rows. If either count is off, a newline got into a cell.

Read the whole diff once for the privacy rule: no names, no titles, no URLs outside `example.com`
and the public repo, and no machine paths.

- [ ] **Step 5: Commit.**

```bash
cd <worktree> && git add CLAUDE.md docs/goals/TODO.md docs/goals/memory-evolution.md \
  docs/superpowers/plans/2026-09-24-r4-foundations-back.md && \
git commit -F - <<'MSG'
docs: round 4 foundations (backend) — per-turn models, recorded_ts, /agents/setup, Apple Calendar (G49, G76, G142)

CLAUDE.md learns the capture's two new keys and that nothing else is read,
the read-time model join, /agents/setup and the 6 s probe, the calendar-local
channel, the capped timeline participants and install.md. TODO ruling 11 lifts
G49's model reservation for harness writes (owner, 2026-09-24) with its
revisit triggers; G49 and G76 rows updated; new row G142.

<attribution lines from your session's system reminder>
MSG
```

---

## Not in scope

- **Any Swift or app code.** That is `feat/r4-foundations-app`'s work. It includes:
  - decoding `participantsTotal` and drawing "+N more" chips;
  - the model/effort chips and the "model not shared by this app" copy;
  - the Settings/Welcome setup UI and the Claude-app config merge;
  - the EventKit reader;
  - the `calendar-local` display name and mark;
  - SMAppService, `SceneClock`, the LaunchAgent script, onboarding, the Home animation, Clusters
    and the entity card.
- **The conversation row's `model`** (`GET /conversations`) stays null. The model is per turn
  (the Reader's `agent`) and per claim.
- **No backfill** of `model`/`effort` onto episodes captured before this change. A session gains
  them on its next grown Stop.
- **No reading of a chat export's model** (e.g. ChatGPT's `model_slug`). Only the harness capture
  records models.
- **A Codex MCP write stays unjoined.** Codex exposes no session id to an MCP server (see Known
  limits).
- **The MCP text surfaces** (`cicada_recall`, `cicada_get_perspective`, `cicada_project`) do not
  name models.
- **`scripts/doctor.sh`'s fresh-bank checks** (G76's prerequisite) are not fixed. `install.md`
  avoids looping on them.
- **The demo generator** gains no model sidecars. Every demo `authorModel` is null.
- **ICS subscriptions** are unchanged, and there is no EventKit on the backend. Recurring events
  are not expanded server-side (the app posts occurrences), and there is no attendee → person
  promotion here.
- **No Sleep gate** on the calendar route. It stages episodes only, like a folder sync.

## Known limits (disclosed, not bugs)

- **Codex MCP writes:** `mcp/server.py` mints `CLAUDE_CODE_SESSION_ID` → `CICADA_SESSION_ID` →
  `ses_*`, and Codex sets neither. So `authorModel` is null for a Codex MCP write, even though its
  captured turns show models in the Reader.
- **The prompt cap:** `setup_prompt` stays ≤ 1,200 characters for a checkout path up to about 60
  characters. A longer path can exceed it rather than shorten a command (R4B-11).

## Flags for the app track (the orchestrator relays these; no contract shape changed)

1. **Additive beyond C3's list:** `ClaimModel.recordedTs`. `EvidenceModel.model/effort` also
   appear on `/episodes/{id}/citations` rows, because that model is shared. Every new optional
   field goes on the wire as an explicit `null` when unset, never as an absent key. That includes
   `/agents/setup`'s `prompt`/`argv`/`display`/`deeplink`/`config`/`note`.
   - **C2's population is narrower than its wording (R4B-16).** Only writes that arrive through
     the MCP seam carry `recorded_ts`: stdio and remote `cicada_write_claim`,
     `cicada_note_progress`, `cicada_retract_claim` and `cicada_record_watch`. In-process
     `agentic_write` callers (Telegram, Wispr Flow, the demo) stamp none. The field stays
     optional, so its shape is unchanged.
   - **`agent` on `/episodes/{id}/text` (R4B-15)** is the most recent agent turn's model/effort,
     or `null` when that turn names neither. It never falls back to an older turn.
2. **`GET /agents/wiring` can now take up to ~6 s.** The app's request timeout for it must exceed
   that.
3. **`GET /agents/setup`** returns both steps for Claude Code and Codex even when one is done, and
   the prompt tells the agent that's fine. `argv` equals `/agents/wiring`'s for an unwired
   harness.
   - Cursor's `deeplink` uses the same bytes `ConnectView` builds.
   - `config.path` is `~`-relative; the app expands it.
   - `kind: "remote"` is never produced this round.
4. **`calendar-local` appears in `GET /sources/channels`**, appended after the fixed ids, before
   any folder rows, and always present. The app's display-name table and mark map need:
   - `calendar-local` → "Apple Calendar";
   - the installed Calendar app's icon (bundle id `com.apple.iCal`), never a committed Apple mark;
   - the Sources catalog id `calendar-local`, and the origin `calendar-local` (the catalog row's
     `mark` is `calendar-local`, an `OriginIconography` key the app must add).
   - **Its row carries `actions: ["sync", "manage"]`.** `ChannelActions.syncRoute` needs a
     `calendar-local` handler that runs the EventKit reader and posts the window. Without it the
     app's "Sync now" throws "Unknown channel calendar-local". `ChannelSyncRoutingTests.registrySyncIds`
     must gain the id too, as the backend's `APP_SYNC_ROUTED` (`test_folder_source.py`) now does.
5. **`POST /sources/calendar-local/sync`:**
   - One request must carry the WHOLE window. A tombstone applies only to calendars named in that
     request.
   - More than 5,000 events → 413. `window.from`/`to` must carry an offset.
   - The response `bank` is the bank's folder name.
6. **`projects-demo.json` was regenerated twice** (Task 1: `participantsTotal`; Task 4: the claim
   and evidence fields). The app track must not edit it. Its decoders stay lenient.

---

## Verification the orchestrator runs at the end

1. **The full backend suite.**
   `cd <worktree> && api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider`
   It must report 0 failures: the baseline's 3775 passed + 1 skipped, plus this track's new
   tests. The one known order-dependent case follows the Global Constraints rule.
2. **`/agents/setup` for each harness,** on a scratch backend (never the live one). `<scratch>` is
   a scratchpad folder:

```bash
cd <worktree> && mkdir -p <scratch>/memory <scratch>/home && \
CICADA_API_AUTH=off CICADA_HOME=<scratch>/home CICADA_MEMORY_PATH=<scratch>/memory \
CICADA_ALLOW_CONNECTOR_FETCH=off CICADA_TELEMETRY=off \
api/.venv/bin/python -m uvicorn api.main:app --host 127.0.0.1 --port 8791   # run in the background
for h in claude-code codex gemini-cli cursor claude-desktop nope; do
  curl -s -o /dev/null -w "$h %{http_code}\n" "http://127.0.0.1:8791/agents/setup?harness=$h"; done
curl -s "http://127.0.0.1:8791/agents/setup?harness=claude-code" | api/.venv/bin/python -m json.tool
```

   Expected: five `200`s and one `404`. The claude-code prompt must be ≤ 1,200 characters and
   name exactly the two `display` commands. Stop the server afterwards.
3. **A synthetic Stop-hook round trip** with model/effort in the sidecar. It never touches a real
   transcript. Every `CICADA_*` variable is set in the shell BEFORE Python starts. A standalone
   script has none of `conftest.py`'s fixtures, and an unset `CICADA_HOME` would make the owner
   resolver and the ledger read and write the real `~/.cicada`:

```bash
cd <worktree> && mkdir -p <scratch>/home && \
CICADA_API_AUTH=off CICADA_HOME=<scratch>/home CICADA_TELEMETRY=off CICADA_ALLOW_CONNECTOR_FETCH=off \
CICADA_ALLOW_LOGO_FETCH=off api/.venv/bin/python - <<'PY'
import json, os, tempfile
from pathlib import Path
from fastapi.testclient import TestClient
from api import config, main
from api.services import markdown_parser, transcript_capture as tc
root = Path(tempfile.mkdtemp(dir="<scratch>")); sid = "12345678-aaaa-4bbb-8ccc-1234567890ab"
proj = root / "projects" / "-home-example-alpha"; proj.mkdir(parents=True)
(root / "memory" / "episodes").mkdir(parents=True)
tc.harness_root = lambda h: proj.parent
line = lambda o: json.dumps({"sessionId": sid, "cwd": "/home/example/alpha", **o})
(proj / f"{sid}.jsonl").write_text("\n".join([
  line({"type": "user", "timestamp": "2026-09-24T10:00:00.000Z", "message": {"role": "user", "content": "Plan alpha"}}),
  line({"type": "assistant", "timestamp": "2026-09-24T10:00:05.000Z", "effort": "xhigh",
        "message": {"role": "assistant", "model": "claude-opus-5-5", "content": [{"type": "text", "text": "Planned."}]}}),
]) + "\n")
os.environ["CICADA_MEMORY_PATH"] = str(root / "memory")
config.get_settings.cache_clear()
r = TestClient(main.app).post("/capture/transcript", json={"harness": "claude-code", "session_id": sid,
      "transcript_path": str(proj / f"{sid}.jsonl"), "effort": "high"})
print(r.status_code, r.json()["status"])
print(markdown_parser.parse(root / "memory" / "episodes" / f"{r.json()['episodeId']}.md").frontmatter["turns"])
PY
```

   Expected: `200 created`, and a sidecar whose agent entry reads
   `{'offset': …, 'ts': '2026-09-24T10:00:05+00:00', 'speaker': 'assistant', 'model': 'claude-opus-5-5', 'effort': 'xhigh'}`.
   The transcript's `xhigh` wins over the hook's `high`.
4. **Timeline size on a synthetic 600-participant project.** The demo generator commits and
   resolves the owner, so the same environment as step 3 applies:

```bash
cd <worktree> && mkdir -p <scratch>/home && \
CICADA_API_AUTH=off CICADA_HOME=<scratch>/home CICADA_TELEMETRY=off CICADA_ALLOW_CONNECTOR_FETCH=off \
CICADA_ALLOW_LOGO_FETCH=off api/.venv/bin/python - <<'PY'
import sys, tempfile
from pathlib import Path
sys.path.insert(0, "api/tests")
from test_timeline_participants_cap import CLAIM_ID, _bank, _build
for n in (13, 600):
    tl = _build(_bank(Path(tempfile.mkdtemp(dir="<scratch>")), n))
    item = next(i for i in tl.items if i.id == CLAIM_ID)
    print(n, len(tl.model_dump_json(by_alias=True)), len(item.participants), item.participants_total)
PY
```

   Expected: both bodies within 1 KB of each other, `12` shown and totals `13` / `600`.
5. **A diff read.** `git log --oneline dev..HEAD` should show 7 commits. Then:
   - `git diff dev --stat` should touch no Swift source, only the regenerated fixture.
   - `git diff dev -U0 | grep -nE '^\+.*/Users/[A-Za-z]'` should print nothing: no author-machine
     path in any added line. Synthetic test paths use `/opt/example-…` and `/home/example/…`.
