# G141 capture side: PJ-0, PJ-4, and capture never writes into a demo bank (Track PJ-a) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Three backend fixes on the capture side of G141, each $0 and engine-free.

1. **PJ-0: Sleep keeps what it hears.** Stage 5.56 keys every claim through Stage 2's own `name_to_id`, so a
   claim lands on the same page as its edge. "The user" maps onto the `owner: true` page. A claim whose
   subject still has no page is counted and logged (as counts), where today it disappears under a false
   comment.
2. **PJ-4: the Stop hook writes per-turn times.** A Claude Code or Codex episode carries G118's
   `turns: [{offset, ts, speaker}]` sidecar instead of an integer count, so a session resumed on day 3 dates
   its day-3 turns to day 3.
3. **Capture never writes into a demo bank.** A bank knows it is the demo. The Stop hook saves the session
   into the real bank that was open most recently, or answers 409. Every other capture writer refuses in
   plain words. The demo generator still writes its own made-up episodes.

**Architecture:** PJ-0 turns the resolver's edge rule into one function, `entity_resolver.endpoint_id`.
`resolve` also returns Stage 2's map, and `claim_pipeline` builds a subject resolver on top of it (owner surfaces, then the
map, then `sanitize_id`). PJ-4 reuses `episode_staging.stamps_for`, the one writer of the sidecar shape:
`transcript_capture._body` already renders the stager's `"{marker}: {text}"` line byte for byte. The demo
guard is one pure module, `api/services/demo_guard.py`, that answers "is this bank the demo?" from the bank
directory alone. It is applied at every capture entry point: the Stop-hook router (redirect), the transcript
service, the five MCP write tools, the remote runtime, the Telegram ingest, the intake's target bank, one
FastAPI route dependency on the 16 POST/PUT routes under `/capture/` and `/sources/` that take something in,
and Sleep's tail.
`bank_registry` gains a `last_active_at` stamp and a `capture_bank` answer for the redirect.

**Tech Stack:** Python 3.12 / FastAPI 0.135.3 / Pydantic, pytest; markdown + git bank. **No app changes, no
Swift.**

**Spec:** `docs/superpowers/specs/2026-09-23-g141-project-timelines-design.md`:
- §2 (the page-less and Stop-hook rows);
- **R-PJ16** and **R-PJ17** (binding);
- §14 Tests (PJ-0, PJ-4);
- §15 Slices;
- §16 Not in scope.

Backlog rows: **G141** (this track), **G117** (the demo bank), **G118** (spans, R-PB4), **G105** (the Stop
hook), **G114** (writer hygiene), **G135** (remote writes). The round-3 spec
(`2026-09-23-round3-meadow-reach-provenance-design.md`) adds nothing binding here beyond the standing rails.
`docs/design/DESIGN_RULES.md` does not apply: nothing here is UI, so no commit cites a DR id.

---

## What the code actually does today (verified at `feat/g141-capture-side` @ `8fde352`)

**PJ-0: the page-less claim loss.**
- `api/services/entity_resolver.py:116`: `name_to_id` is a **local** of `resolve`.
  - Existing names are registered at `:120`, a "same" match at `:187` and a promotion at `:247`.
  - Relationship edges resolve through it at `:319-330`: an exact lookup, then the first `fuzz.ratio > 85`.
  - `:376-380` returns `changes`, `relationships` and `episode_cooccurrences`, and **not the map**.
- `api/services/entity_extractor.py:530-531`: `subject = sanitize_id(source)` / `obj = sanitize_id(target)`,
  so a claim is keyed by the raw name. Stage 2 matched the short "Hana" to `hana-example`, but the claim keys
  `hana`, which has no page.
- `api/services/claim_pipeline.py`:
  - `:28-30`: the docstring says "a page-less claim simply waits for its subject to be promoted".
  - `:90-92`: `existing_entities` is documented as unused.
  - `:107`: `entities_to_claims(extracted, memory_path)`.
  - `:139-144`: the page-less skip, under the comment "it will be **re-emitted next cycle** once the page
    exists". This is false: the cycle marks its episodes processed (`sleep_cycle._mark_episodes_processed`,
    `:1657`, called at `:1378`), so nothing re-extracts them.
  - `:160-165`: the log line counts subjects, not claims.
- `api/services/sleep_cycle.py`:
  - `:1194-1197`: Stage 2's call (`resolved_result = await resolve(...)`).
  - `:1298`: `run_claim_pipeline(extracted, existing, memory_path, settings)`.
  - `:1324-1330`: the 5.56 log line.
  - `SleepState` counters: `:55-56`, reset at `:950-951`.
  - The `sleep_run` ledger refs: `:2009-2018`.
- Stage 1's prompt speaks of "the user" (`entity_extractor.py:56-64,104,125`). Nothing maps that surface to
  the owner (a grep for owner aliases in Stage 1/2 finds none).

**PJ-4: the Stop hook's count.**
- `api/services/transcript_capture.py`:
  - `:134-137`: `_body` renders `"\n".join(f"{t.role}: {t.text}")`.
  - `:249-262`: the create path writes `"turns": len(conv.turns)` (`:261`).
  - `:281-289`: the update path writes it again (`:284`).
  - The episode `timestamp` is `_utc(conv.started_at)` (`:247`) and is kept through every rewrite (the `:278`
    comment).
- `api/services/transcript_extract.py:76-80`: `Turn` already carries each turn's `ts`.
- `api/services/episode_staging.py`:
  - `:170-173`: `_line` is `f"{turn.speaker}: {text}"`, **the same rendering as `_body`**.
  - `:176-188`: `_stamps` builds the sidecar. It keeps a turn only when the turn has a time, normalises it to
    aware UTC, and caps the list head-stable at `MAX_TURN_STAMPS = 500` (`:68`).
  - `:207-216`: `stamps_for(draft, body)` returns the sidecar only when `body` is exactly the draft's
    rendering, and `[]` otherwise.
  - `:249-265`: `_apply_common` pops `turns` and then sets it last.
- `api/services/evidence.py`:
  - `:326-328`: `turn_starts`.
  - `:399-428`: `turn_stamps` reads a non-list `turns` as `{}`.
  - `:431-449`: `turn_at`.
- **Every `turns` key in non-test code** (`grep -rn "[\"']turns[\"']" api mcp`), by file:
  - `transcript_capture.py:261,284`: writes the int.
  - `episode_staging.py:263,265`: writes the list.
  - `evidence.py:45`: the `__all__` name.
  - `evidence.py:410`: reads, and treats a non-list as no stamps.

  **No reader uses the integer.** `episodes.py:84`'s `turn_count` is `turn_at(...)["of"]`, counted from the
  body's marker lines, not from the frontmatter. The Swift `turns` (`Models/Evidence.swift:246`) is the
  derived wire list from `/episodes/{id}/text`, not the frontmatter.
- `api/tests/test_capture_transcript.py:132,164` pin `fm["turns"] == 2` / `== 3`.
- `CLAUDE.md:181-183,346-348,841-842` state the integer count as a rail.

**Demo bank: capture writes into it.**
- `api/services/demo_bank.py:92-106`: `populate` writes **no marker**. The one generator-specific trace is
  `_commit_history`'s `git config user.email demo@cicada.example` (`:367-374`), in the bank's own
  `.git/config`.
- `api/routers/banks.py:235-265`: `POST /banks/demo` = `create_bank(root, "demo")`, then `populate`, then
  `activate_bank`.
- `api/services/bank_registry.py`:
  - `:189-216`: `resolve_active_bank_path`.
  - `:393-417`: `create_bank`.
  - `:420-427`: `activate_bank` records nothing about the bank being left.
  - `:526`: `rename_bank` moves the record whole (`banks[new_slug] = banks.pop(name)`).
- `api/routers/capture.py:148-184`: `POST /capture/transcript` writes into `settings.memory_path`, the ACTIVE
  bank, whatever it is. `:41-133`: `POST /capture/telegram` does the same through
  `telegram_capture.ingest_telegram_update` (`api/services/telegram_capture.py:197-269`).
- The MCP write tools: `api/services/mcp_tools.py` `save_url:273`, `record_watch:370`, `write_claim:867`,
  `retract_claim:1020`, `save_episode:1758`, all over `ctx.memory_path()`.
  - Stdio resolves the active bank per call (`mcp/server.py:691-713`).
  - Remote resolves it through `get_settings().memory_path` (`api/remote/runtime.py:134-137`). Its gates are
    `:225-240`, and the write set is `api/remote/catalog.py:47` `WRITE_TOOLS`.
- `api/routers/intake.py:356-368`: `resolve_target` picks the target bank. It is shared by
  `/intake/import`, `/intake/sniff`, `/banks/{name}/import` and `/conversations/upload`.
- `api/services/sleep_cycle.py:875-897`: the tail's guarded branch polls connectors (machine-global
  credentials), feeds/calendars, the link backfill, papers and the Wispr to-do replay into whatever bank Sleep
  ran on.
- **The live route set.** Enumerated from `main.app.routes` on this base, the POST/PUT routes under
  `/capture/`, `/sources/` and `/intake/` are these 22:
  - `/capture/`: `POST /capture/local-source/wispr-flow`, `PUT /capture/local-source/wispr-flow/settings`,
    `POST /capture/telegram`, `POST /capture/transcript`.
  - `/intake/`: `POST /intake/import`, `POST /intake/sniff`.
  - `/sources/` (POST): `/sources/calendars`, `/sources/connectors/{connector_id}/authorize`,
    `/sources/connectors/{connector_id}/sync`, `/sources/feeds`, `/sources/folders`,
    `/sources/folders/{folder_id}/sync`, `/sources/poll-calendars`, `/sources/poll-feeds`, `/sources/rss`,
    `/sources/save`, `/sources/sync-bookmarks`, `/sources/sync-notes`, `/sources/sync-safari-tabs`,
    `/sources/upload`.
  - `/sources/` (PUT): `/sources/connectors/{connector_id}/credentials`, `/sources/folders/{folder_id}`.

  Two more write episodes from outside those prefixes: `POST /banks/{name}/import` and
  `POST /conversations/upload`, both through `intake.import_bytes`.
- **`CLAUDE.md` has no demo-bank sentence.** `grep -n -i "demo\|synthetic" CLAUDE.md` finds nothing. The
  Awake section says "Six rails hold across all of them" (`:147`).
- FastAPI 0.135.3 runs a **route-level** dependency before body validation. This was checked on this venv: a
  gate on a JSON-body route, an `UploadFile` route and an optional-body route each answered the gate's 409 to
  an empty POST, never a 422. It does **not** run before the body is *read*: `fastapi/routing.py` awaits
  `request.form()` / `request.json()` first and only then calls `solve_dependencies` (sub-dependencies,
  route-level ones first, then params and body validation). So a malformed JSON body still answers 422 before
  the gate, and an upload's bytes are received before the 409. Nothing reaches the bank either way.
- **Two gated routes read the machine's own data when called with no body.** `POST /sources/sync-bookmarks`
  falls back to `bookmark_sync.sync_from_local_files` (the real Chrome/Safari bookmark files,
  `sources.py:428`) and `POST /sources/sync-notes` to `notes_sync.sync_from_local_notes` (Notes.app through
  `osascript`, `sources.py:883`). `POST /sources/connectors/{id}/sync` runs the adapter with
  `allow_fetch=True`. A bodiless test call that reaches a handler (the red phase, or a gate removed on purpose)
  must never reach those, so Task 4's test file stubs the two local readers and names a connector that does
  not exist.
- **`dev` has moved since the base, docs only.** `git diff --stat 8fde352 dev -- api mcp` is empty, so every
  code anchor above holds. But `ef4c8d8` (on `dev`, not in this base) records the owner's rulings on the G141
  DECIDEs (2026-09-23): (c) **yes**, Sleep holds an unpromoted subject's claims with the pending entity and
  writes them on promotion, as a new slice **PJ-0b** after PJ-0; and R-PJ16 is accepted. The same commit
  rewrote the TODO.md DECIDE paragraph and the G141 row's carry-forward. Task 5 therefore merges `dev` before it
  edits any doc (its Step 0).

**Baseline:** backend **3167 passed** on `dev` (2026-09-23). Swift is not touched by this track.

---

## Global Constraints

- **Where to work.** Work ONLY in `<worktree>`, the track's worktree `.worktrees/pja` under the repo (branch
  `feat/g141-capture-side`, based on `dev` @ `8fde352`).
  - Every shell command is `cd <worktree> && <cmd>`, with the absolute path substituted. zoxide hijacks a
    relative `cd`; ignore its stderr warning.
  - Never pass an unquoted `--include=*.ext` to grep (zsh globs it). Pipe through `grep "\.py:"` instead.
- **Never read a real bank.** NEVER read `<repo>/memory` (any bank), `~/.cicada`, `~/Library` or
  `~/.claude/projects`. Every fixture is synthetic: `alpha-project`, `bob-example` (the owner),
  `hana-example`, `lab-cluster-example`, `example.com`, `/home/example/...` paths.
- **Python.**
  - One file: `cd <worktree> && api/.venv/bin/python -m pytest <files> -q -p no:cacheprovider`.
  - The full suite, `api/tests`, must report **0 failures** (≥ 3167 passed).
  - `test_agent_provenance.py::test_a_decay_only_change_lands_in_its_own_cicada_authored_commit` is
    order-dependent. If it is the ONLY red, re-run it alone and report both results.
- **Git hygiene.** Never `git add -A`; stage named files only. Never commit `memory/`, `logs/`,
  `.claude/settings.json`, `api/.venv` or `*-report.md`. No push, no new branches or worktrees, no subagents.
  Ignore Devin/PR comments. The one merge this track makes is Task 5 Step 0 (local `dev` into this branch,
  docs-only since the base), so the doc edits land on the owner's current text instead of conflicting with it.
- **Commit messages.** End every commit message with the attribution lines the implementing session's system
  reminder names (`Co-Authored-By: …` and `Claude-Session: …`).
- **No app changes.** Nothing under `app/` moves. `git diff --stat dev -- app/` must be empty at the end.
- **Sleep-safety.** Nothing here calls an LLM. The guard and the sidecar are file reads and string work.
  Transcripts are read ONLY by `transcript_capture` (the G105 path), exactly as today.
- **Telemetry is ids, enums and counts.** The new `sleep_run` refs are integers. The `capture` refusal is the
  enum `demo_bank`. The remote status is the enum `demo`. A subject id is a slug of a name, so it is **never
  logged and never put in the ledger** (R-CS3).
- **Portability.** Nothing keys on the bank's *name* "demo" (R-CS10). No owner name, no author-machine path.
- **Privacy in docs** (standing, 2026-09-02). No real names, no episode titles, no conversation text. The
  owner's example uses `<person-a>` / `<demo-x>`.
- **Docstrings explain why** and cite the row or ruling (`G141 PJ-0`, `R-PJ16`, `R-CS12`, …). Match the
  density of the file you touch.
- **Line numbers drift.** The anchors above are from `8fde352` and move as tasks land. Read the cited code
  before every edit.

---

## Rulings (binding)

R-PJ16 and R-PJ17 hold as the spec writes them, with the owner's 2026-09-23 rulings on `dev` (`ef4c8d8`): R-PJ16
is accepted, and R-PJ17's hold is ruled yes as slice PJ-0b (R-CS4). Everything below is a decision this plan takes where the
brief or the spec left a choice, or where the spec and the code disagree (the code is the truth), with the
reason.

**R-CS1: a claim endpoint is keyed by ONE precedence.**
- The order is:
  1. an owner surface, but only when an `owner: true` page exists (R-CS2);
  2. Stage 2's map through `entity_resolver.endpoint_id` (exact, then the first `fuzz.ratio > 85`, the rule
    the edges at `:319-330` always used, now one function);
  3. `sanitize_id(name)`, the pre-PJ-0 key.
- The owner surface comes first because a Stage-1 "User" mention that Stage 2 happened to promote into a
  junk `user` page must not win over the person's page.
- `endpoint_id` replaces the two inline loops byte-for-byte in behaviour. The one difference: a `None`
  endpoint no longer raises on `.lower()`.
- `entities_to_claims` gains a keyword-only `resolve_id` callable, not a `name_to_id` argument, so Stage 1's
  module never learns Stage 2's internals. Without it, every hermetic caller keeps `sanitize_id`.

**R-CS2: the owner page comes from Stage 2's `existing` list.**
- `run_claim_pipeline`'s `existing_entities` argument was documented as unused. It now supplies the page whose
  frontmatter says `owner: true`.
- Two owner pages can exist (G117 R3's disclosed re-onboarding gap). Then the one
  `owner_identity.resolve_observer` names wins, else the first by id.
- `OWNER_SURFACES = {"user", "the user", "me", "myself", "i"}` is **closed**. Anything else that meant the
  person and still misses is counted, and M3 reads the count.
- With no owner page, "the user" is page-less and counted. No `user` or `the-user` page is ever invented.

**R-CS3: "counted and logged (ids only)" means counts at INFO and opaque claim ids at DEBUG.**
- A subject id is a slug of a name, and in the owner's bank that is a person's name. So it is never logged
  and never sent to the ledger.
- `run_claim_pipeline` returns `claims_page_less` (int) and `page_less_subjects` (sorted ids) in memory only,
  for tests and for the R-PJ17 seam.
- `SleepState` gains two internal counters, not exposed on `/sleep/status`. The `sleep_run` ledger row gains
  `claims_page_less` and `subjects_page_less`, so M3 ("page-less drops per cycle") is measurable by a
  count-only script.
- This satisfies spec §14's "logs a count, with no text".

**R-CS4: the R-PJ17 seam is `claim_pipeline.hold_page_less(subject, claims, memory_path) -> int`.**
- The owner ruled the DECIDE on 2026-09-23 (on `dev` after this base, `ef4c8d8`): **yes**, hold the claims with
  the pending entity and write them on promotion, as its own slice **PJ-0b** after PJ-0. The hold changes the
  pending store, so it is not built here.
- Here the seam returns 0, and its docstring names the ruling and PJ-0b.
- The pipeline counts `len(claims) - held`. PJ-0b changes this one function body (and the pending store) and
  nothing else in the pipeline moves.
- No pending-store change, no file written.

**R-CS5: claims inherit Stage 2's matches, false merges included. This is disclosed, not fixed.**
- `_find_direct_candidate_match` already merges any name within `fuzz.ratio > 85` of an existing page. For
  example, "Tool Example B" merges into `tool-example-a` at ratio 93.
- The claim now follows Stage 2 there, as its edge already did. Tightening Stage 2's matcher is G98's.

**R-CS6: PJ-4 builds the sidecar with `episode_staging.stamps_for`. The spec said this was impossible, and
the code says otherwise.**
- R-PJ16 says `transcript_capture` "renders `"{role}: {text}"` lines … not `episode_staging`'s line renderer,
  so `_stamps` cannot be reused". But `_body` (`transcript_capture.py:134-137`) and `_line`
  (`episode_staging.py:170-173`) produce the **same bytes**: `"{marker}: {text}"` joined by `"\n"`.
- So the Stop hook builds an `EpisodeDraft` of `episode_staging.Turn(text, speaker=role, ts)` and calls the
  public `stamps_for(draft, body)`. That gives:
  - one writer of the shape, as `evidence.turn_stamps`'s docstring demands ("Written by ONE writer … which IS
    the coordination contract");
  - the same 500 head-stable cap and the same aware-UTC normalisation;
  - `[]` rather than offsets into text the body does not hold.
- The brief's "via `evidence.turn_starts`" is kept as the test. Every stamped offset is in `turn_starts(body)`,
  and the offsets equal the rendering's line starts even when a person's message contains a line that only
  looks like a marker.

**R-CS7: no separate count key.**
- The re-grep (above) finds no integer reader, so per R-PJ16 the count simply becomes `len(turns)`.
- `CaptureResult.turns_user/turns_assistant` and the `capture` ledger's `turns_user/turns_assistant` still
  carry the real turn counts.
- A source lint pins that exactly three modules spell a quoted `turns` key: `episode_staging.py`,
  `evidence.py` and `transcript_capture.py`. A future count reader has to face R-PJ16's `turn_count:`
  instead of reusing `turns`.

**R-CS8: the episode `timestamp` stays the session's start.**
- The id's date, the queue order and G104's one-episode-per-session identity all read it. Only the sidecar
  dates turns.
- A Stop-hook episode written before PJ-4 is **not backfilled**. It gains the list on its session's next body
  change, because the unchanged-hash path writes nothing: the Stop-fires-every-reply no-churn rule.
- Until then its int reads as no stamps.

**R-CS9: a turn past the cap carries no stamp.**
- This slice pins `turn_at(...)["ts"] is None` for turn 501.
- "Anchors with basis `episode`" is how PJ-3's not-yet-built `when.py` reads that `None`, so this slice pins
  the input to that rule. The spec's M5 counts sessions over the cap.

**R-CS10: a demo bank is marked in the bank itself: `<bank>/_bank.yaml`, `kind: demo`.**
- `demo_bank.populate` writes it FIRST, so a populate that dies half-way still leaves a refused bank.
  `_commit_history` commits it alone, as `cicada`, before any other commit. A manifest left untracked would be
  swept by the next `git add -A` under a model's name (G85).
- **Why in the bank, not a `banks.yaml` key:**
  - it travels with a duplicate, a rename, an export and a hand copy (a copy of synthetic content is still
    synthetic);
  - every writer holds only a bank path (the stdio MCP server has no registry handle);
  - the check is one read.
- **Legacy signal:** a demo generated before the manifest is recognised by the generator's own identity,
  `email = demo@cicada.example`, in `<bank>/.git/config`. `populate` has written this since G117 (the brief's
  "whatever marker populate already writes"). No migration and no write is needed.
- `demo_guard.GENERATOR_EMAIL` becomes the one spelling, and `_commit_history` uses it.
- **Never the bank's name:** a person may call a real bank "demo".
- A malformed manifest reads as "not demo". This fails open for a real bank's capture, and the git identity
  still catches every generator-made bank.

**R-CS11: which real bank was open most recently.**
- `activate_bank` stamps `last_active_at` (aware UTC) on the bank being **left**. Re-activating the active
  bank stamps nothing.
- `most_recent_real_bank(root)` considers the registered banks that are not active, exist on disk and are not
  demo. It returns the one with the latest stamp.
- With no stamps (a registry from before this change), it returns the only real bank if there is exactly one.
  That is the common install: the legacy `default` plus `demo`. With several, it returns **`None`**: Cicada
  never guesses which of two real memories a conversation belongs to.
- `/banks` is unchanged. Its ETag already moves on every activation (the `banks.yaml` mtime).

**R-CS12: the Stop hook redirects; everything else refuses.**
- The Stop hook's session is not the demo's, and nothing else captures it, so `POST /capture/transcript`
  asks `bank_registry.capture_bank(root)`.
  - A real active bank is its own target.
  - With the demo active, the target is the real bank left most recently. The response carries `bank` and
    `redirectedFrom`.
  - With no such bank, `409` with `demo_guard.HOOK_REFUSAL`. Nothing is read, and a `capture` ledger row
    records `refused` / `demo_bank`.
- A 409 loses nothing for a session that goes on: every Stop re-captures the whole session, so the first reply
  after switching back saves it in full. A session that gets no further reply stays unsaved until it is resumed
  and replied to — disclosed, not fixed. The 409 needs a registry with no `last_active_at` stamp and two or more
  real banks, which only an install that upgraded with the demo already open can have: the first switch after
  this change stamps the bank it leaves.
- `capture_transcript` itself also refuses a demo path before validating anything, as a guard for any future
  caller. The router relies on that refusal for the ledger row instead of writing a second recorder.
- The hook's log line names the bank a redirected session went to: a bank name, never a path or content.

**R-CS13: the five MCP write tools refuse in a demo bank.**
- The five are `catalog.WRITE_TOOLS`: `cicada_save_episode`, `cicada_save_url`, `cicada_record_watch`,
  `cicada_write_claim` and `cicada_retract_claim`.
- Each answers `demo_guard.AGENT_REFUSAL`, which tells the agent what to tell the person.
- The check lives in `mcp_tools`, so stdio and remote share one implementation. The remote runtime also
  answers first with its own status enum `demo` (beside `busy`), so the `remote_call` ledger row says why
  nothing was written.
- The check reads the bank the tool already resolved. `write_claim`, `retract_claim`, `save_episode` and
  `record_watch` each call `ctx.memory_path()` once and say why ("One bank resolution per call: the write, the
  ledger row and the commit must all name the same bank"), so the guard tests that same path right after the
  resolution instead of resolving a second time. `save_url` resolves nothing before its backend path, so it
  checks `ctx.memory_path()` first.
- **Not gated:**
  - `cicada_resolve_inbox`: it answers a demo question about made-up people, which is the demo working;
  - `cicada_mark_processed`: it flips a flag and holds no content;
  - every read.

**R-CS14: Telegram answers 200 with a reply, never an error.**
- Telegram retries a non-2xx for hours. A retry that lands after the person switches back would save a
  message they were already told was not saved.
- `ingest_telegram_update` returns `kind: skipped, reason: demo_bank, ack: TELEGRAM_ACK`, and the person
  resends.

**R-CS15: one dependency gates every other HTTP capture route.**
- `refuse_capture_into_demo` lives in `api/routers/capture.py`, beside the capture routes. It answers `409`
  with `demo_guard.REFUSAL` before the body is validated and before any handler code runs (see the FastAPI note
  above: FastAPI has already read the body by then, but nothing of it reaches the bank).
- It rides on the 16 POST/PUT routes under `/capture/` and `/sources/` in the `GATED` table (Task 4). That
  includes subscription and folder registration and the Wispr settings: each writes a real source's choices
  (a folder's project page, the person's speaker names) into the bank.
- `HANDLED_ELSEWHERE` names the other 6 and why:
  - `/capture/transcript` redirects;
  - `/capture/telegram` replies;
  - `/intake/import` and `/intake/sniff` check their **target** bank (the sniff stages nothing, and only a chat
    export reaches `resolve_target`);
  - the connector `credentials` and `authorize` routes take nothing in: `credentials` stores the secret in
    `~/.cicada/secrets.env` and only restamps the bank's `sync_state.json` (`sync_state.record_credentials_changed`,
    a timestamp, no content); `authorize` mints a sign-in link.
- The intake checks the bank it writes INTO (`resolve_target`, before the scaffold). So `?bank=default` into
  your own memory still works while the demo is open. `/banks/{name}/import` and `/conversations/upload`
  inherit this through `import_bytes`.
- A structural test fails the build for any new POST/PUT under `/capture/`, `/sources/` or `/intake/` that is
  in neither table.

**R-CS16: a demo bank's Sleep tail takes nothing in from outside.** (Stage 5.57's in-cycle link enrichment is
not a tail step and still runs; it only fetches links the demo already holds — see Not in scope.)
- Sleep on the demo consolidates its own made-up episodes: that is what the demo is for.
- But the tail's outside-world steps are skipped with one log line:
  - the connector poll (the credentials are machine-global, so it would pull the person's real saves in);
  - the feed/calendar poll;
  - the link backfill;
  - the paper lookup;
  - the Wispr to-do replay.
- Expiry, the state refresh, logos and the question refresh still run.

**R-CS17: the generator is exempt by construction, and there is no choke-point guard.**
- `populate` writes through `markdown_parser`, `owner_identity` and `agentic_write.write_claim`, and none of
  them is gated.
- A guard in `episode_ids.next_episode_id` or `episode_staging.stage` would:
  - need an exemption for the generator;
  - miss the Stop hook's in-place rewrite, which mints nothing;
  - turn a refusal into a 500 deep inside a writer.

  The guard lives at the entry points, where a plain answer can be given.

**R-CS18: CLAUDE.md has no demo-bank sentence to "mention it in", and the code is the truth.** Task 4 adds a
seventh Awake rail, "Capture never writes into a demo bank", and changes "Six rails" to "Seven rails".

**R-CS19: code never moves or deletes a leaked capture that is already in a demo bank.** Removal stays manual,
as it was done on 2026-09-23. A freshly generated demo bank is the only source for screenshots, as the spec
already says.

**R-CS20: the four sentences live in one module** (`demo_guard`):
- `REFUSAL` (HTTP/app);
- `AGENT_REFUSAL` (MCP);
- `TELEGRAM_ACK`;
- `HOOK_REFUSAL`.

All are plain and friendly for a non-technical reader, with no jargon, no bank paths and no price. Tests
assert the constants, never a copy of their text.

---

## File map

| File | Task | Responsibility |
|---|---|---|
| `api/services/entity_resolver.py` | 1 | `endpoint_id` (the edge rule as one function); `resolve` returns `name_to_id` |
| `api/services/entity_extractor.py` | 1 | `entities_to_claims(..., *, resolve_id=None)` |
| `api/services/claim_pipeline.py` | 1 | `OWNER_SURFACES`, `_owner_page_id`, `subject_resolver`, `hold_page_less`; keyed emission; the page-less count; the false comments gone |
| `api/services/sleep_cycle.py` | 1, 4 | 1: thread the map, two counters, `sleep_run` refs. 4: the tail skips outside-world steps on a demo bank |
| `api/services/transcript_capture.py` | 2, 3 | 2: `_turn_sidecar`, `_place_turns`, no int. 3: refuse a demo path unread |
| `api/services/episode_staging.py`, `api/services/evidence.py` | 2 | docstrings only: the Stop hook is now a sidecar writer |
| `api/services/demo_guard.py` (new) | 3 | `MANIFEST`, `GENERATOR_EMAIL`, `write_manifest`, `is_demo`, the four sentences |
| `api/services/demo_bank.py` | 3 | manifest first; its own `cicada` commit; `GENERATOR_EMAIL` |
| `api/services/bank_registry.py` | 3 | `last_active_at` stamp; `most_recent_real_bank`; `CaptureBank` + `capture_bank` |
| `api/routers/capture.py` | 3, 4 | 3: the transcript redirect / 409, `bank` + `redirectedFrom`. 4: `refuse_capture_into_demo` |
| `api/hooks/capture.py` | 3 | the log line names a redirected session's bank |
| `api/services/mcp_tools.py` | 3 | `_demo_refusal(memory_path)` on the one bank each write tool resolves |
| `api/remote/runtime.py` | 3 | status `demo` for a write into a demo bank |
| `api/services/telegram_capture.py` | 3 | 200 + `TELEGRAM_ACK`, nothing written |
| `api/routers/sources.py`, `api/routers/local_sources.py`, `api/routers/connectors.py` | 4 | `dependencies=[Depends(refuse_capture_into_demo)]` on the 16 gated routes |
| `api/routers/intake.py` | 4 | `resolve_target` refuses a demo **target** |
| Tests (new) | 1–4 | `test_claim_pipeline_subjects.py`, `test_transcript_turn_stamps.py`, `test_demo_capture.py`, `test_demo_capture_routes.py` |
| Tests (edited) | 2 | `test_capture_transcript.py:132,164` (the pinned int) |
| `CLAUDE.md` | 2, 4 | 2: the three `turns` sentences (R-PJ16). 4: the seventh Awake rail |
| `docs/goals/TODO.md`, `docs/goals/memory-evolution.md` | 5 | after merging `dev`: G141 PJ-0/PJ-4 done (PR placeholder), PJ-0b next; G141 carry-forward; the G117 capture-guard note |

---

### Task 1: PJ-0: Sleep keys claims through Stage 2's ids and counts page-less drops

The branch stays shippable. With no `name_to_id`, every existing caller behaves exactly as before.

**Files:**
- Modify: `api/services/entity_resolver.py`. Add `endpoint_id` above `resolve` (`:20`). The edge block
  `:311-330` uses it. The return at `:376-380` gains the map.
- Modify: `api/services/entity_extractor.py:500-531` (`entities_to_claims`).
- Modify: `api/services/claim_pipeline.py`: the docstring `:26-30`, the imports `:40-50`, new helpers, the
  signature and body `:76-173`.
- Modify: `api/services/sleep_cycle.py` at `:55-56`, `:950-951`, `:1298`, `:1324-1330` and `:2009-2018`.
- Test: `api/tests/test_claim_pipeline_subjects.py` (new).

**Interfaces:**
- Produces:
  - `entity_resolver.endpoint_id(name: str, name_to_id: dict[str, str]) -> str | None`;
  - `resolve(...)["name_to_id"]`;
  - `entity_extractor.entities_to_claims(extracted, memory_path, *, resolve_id=None)`;
  - from `claim_pipeline`: `OWNER_SURFACES`, `subject_resolver(name_to_id, owner_id)`,
    `hold_page_less(subject, claims, memory_path) -> int`, and
    `run_claim_pipeline(..., name_to_id=None)`, whose result gains `claims_page_less: int` and
    `page_less_subjects: list[str]`;
  - `SleepState.claims_page_less`, `SleepState.subjects_page_less`;
  - `sleep_run` refs `claims_page_less`, `subjects_page_less`.
- Consumes `owner_identity.resolve_observer`, `id_utils.sanitize_id` and `thefuzz.fuzz.ratio`.

- [ ] **Step 1: Failing tests.** Create `api/tests/test_claim_pipeline_subjects.py`:

```python
"""G141 PJ-0 (R-PJ17, R-CS1..R-CS4): Sleep keys a claim's subject and object
through Stage 2's own ids — the map its edges already use — maps "the user"
onto the `owner: true` page, and counts (never silently drops) a claim whose
subject still has no page. Synthetic names only."""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from loguru import logger

from api.config import Settings
from api.services import (claim_pipeline, entity_resolver, git_service, markdown_parser, owner_identity,
                          predicates, sleep_cycle, telemetry)
from api.services.claims import parse_claims

REPO = Path(__file__).resolve().parents[2]
EP = "ep_2026-09-22_001"
TS = "2026-09-22T10:00:00+00:00"


def _settings(memory: Path) -> SimpleNamespace:
    return SimpleNamespace(memory_path=memory, litellm_model="gpt-5.4-mini",
                           litellm_disambiguation_model="gpt-5.4-nano", archive_threshold=0.2,
                           decay_nudge_threshold=0.4, sleep_promotion_threshold=2,
                           link_enrich_enabled=False)


def _bank(tmp_path: Path) -> Path:
    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True)
    predicates.install_predicate_map(memory)
    return memory


def _page(memory: Path, entity_id: str, name: str, kind: str = "person", **extra) -> dict:
    fm = {"name": name, "type": kind, "status": "active", **extra}
    path = memory / "entities" / f"{entity_id}.md"
    markdown_parser.write(path, fm, "## Summary\nA synthetic page.")
    return {"id": entity_id, "frontmatter": fm, "body": "## Summary\nA synthetic page.", "filepath": path}


def _extracted(*rels: tuple[str, str, str]) -> list[dict]:
    return [{
        "episode_id": EP, "episode_timestamp": TS, "origin": "claude-code", "entities": [],
        "relationships": [{"source": s, "target": t, "label": label, "source_episode": EP,
                           "source_episode_timestamp": TS} for s, label, t in rels],
    }]


def _pairs(memory: Path, entity_id: str) -> list[tuple[str, str]]:
    body = markdown_parser.parse(memory / "entities" / f"{entity_id}.md").body
    return [(c.subject, c.object) for c in parse_claims(body)]


def _stems(memory: Path) -> list[str]:
    return sorted(p.stem for p in (memory / "entities").glob("*.md"))


# --- keyed through Stage 2 (R-CS1) ------------------------------------------------


def test_endpoint_id_is_the_edge_rule_exact_then_fuzzy():
    table = {"alpha project": "alpha-project", "bob example": "bob-example"}
    assert entity_resolver.endpoint_id("Alpha Project", table) == "alpha-project"
    assert entity_resolver.endpoint_id("alpha projects", table) == "alpha-project"  # ratio 96
    assert entity_resolver.endpoint_id("Zed Unknown", table) is None
    assert entity_resolver.endpoint_id("", table) is None
    assert entity_resolver.endpoint_id(None, table) is None  # type: ignore[arg-type]


def test_stage2_returns_the_map_its_edges_used(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    existing = [_page(memory, "alpha-project", "Alpha Project", kind="project")]

    class _NoIndex:
        def __init__(self, *_a, **_k):
            raise RuntimeError("no vector store in this test")

    monkeypatch.setattr(entity_resolver, "SqliteVecIndexer", _NoIndex)
    extracted = [{"episode_id": EP, "relationships": [],
                  "entities": [{"name": "Alpha Projects", "type": "project", "confidence": 0.8,
                                "source_episode": EP}]}]
    result = asyncio.run(entity_resolver.resolve(extracted, existing, _settings(memory)))
    assert result["name_to_id"]["alpha project"] == "alpha-project"
    assert result["name_to_id"]["alpha projects"] == "alpha-project"  # the direct fuzzy match


def test_a_claim_on_a_stage2_matched_short_name_lands_on_the_matched_page(tmp_path):
    memory = _bank(tmp_path)
    existing = [_page(memory, "hana-example", "Hana Example"),
                _page(memory, "lab-cluster-example", "Lab Cluster Example", kind="tool")]
    # Stage 2 judged the short "Hana" to be the existing person.
    name_to_id = {"hana example": "hana-example", "lab cluster example": "lab-cluster-example",
                  "hana": "hana-example"}
    result = claim_pipeline.run_claim_pipeline(
        _extracted(("Hana", "connects to", "Lab Cluster Example")), existing, memory,
        _settings(memory), now_date="2026-09-22", name_to_id=name_to_id)
    assert _pairs(memory, "hana-example") == [("hana-example", "lab-cluster-example")]
    assert result["claims_page_less"] == 0 and result["page_less_subjects"] == []
    assert _stems(memory) == ["hana-example", "lab-cluster-example"]  # no `hana` page invented


def test_without_the_map_the_same_claim_is_counted_instead_of_vanishing(tmp_path):
    memory = _bank(tmp_path)
    existing = [_page(memory, "hana-example", "Hana Example"),
                _page(memory, "lab-cluster-example", "Lab Cluster Example", kind="tool")]
    result = claim_pipeline.run_claim_pipeline(
        _extracted(("Hana", "connects to", "Lab Cluster Example")), existing, memory,
        _settings(memory), now_date="2026-09-22")
    assert _pairs(memory, "hana-example") == []
    assert result["claims_page_less"] == 1 and result["subjects_skipped"] == 1
    assert result["page_less_subjects"] == ["hana"]


# --- the owner (R-CS2) --------------------------------------------------------------


def test_the_user_lands_on_the_owner_page_as_subject_and_as_object(tmp_path):
    memory = _bank(tmp_path)
    existing = [_page(memory, "bob-example", "Bob Example", owner=True),
                _page(memory, "hana-example", "Hana Example"),
                _page(memory, "lab-cluster-example", "Lab Cluster Example", kind="tool")]
    name_to_id = {"bob example": "bob-example", "hana example": "hana-example",
                  "lab cluster example": "lab-cluster-example"}
    result = claim_pipeline.run_claim_pipeline(
        _extracted(("the user", "connects to", "Lab Cluster Example"),
                   ("Hana Example", "gave a guide to", "User")),
        existing, memory, _settings(memory), now_date="2026-09-22", name_to_id=name_to_id)
    assert _pairs(memory, "bob-example") == [("bob-example", "lab-cluster-example")]
    assert _pairs(memory, "hana-example") == [("hana-example", "bob-example")]
    assert result["claims_page_less"] == 0
    assert _stems(memory) == ["bob-example", "hana-example", "lab-cluster-example"]


def test_the_user_without_an_owner_page_is_counted_never_invented(tmp_path):
    memory = _bank(tmp_path)
    existing = [_page(memory, "lab-cluster-example", "Lab Cluster Example", kind="tool")]
    result = claim_pipeline.run_claim_pipeline(
        _extracted(("the user", "connects to", "Lab Cluster Example")), existing, memory,
        _settings(memory), now_date="2026-09-22", name_to_id={"lab cluster example": "lab-cluster-example"})
    assert result["claims_page_less"] == 1 and result["page_less_subjects"] == ["the-user"]
    assert _stems(memory) == ["lab-cluster-example"]


def test_two_owner_pages_resolve_through_owner_identity(tmp_path):
    memory = _bank(tmp_path)
    existing = [_page(memory, "bob-example", "Bob Example", owner=True),
                _page(memory, "robert-example", "Robert Example", owner=True),
                _page(memory, "lab-cluster-example", "Lab Cluster Example", kind="tool")]
    owner_identity.save_owner({"entity_id": "robert-example"})  # CICADA_HOME is per-test (conftest)
    claim_pipeline.run_claim_pipeline(
        _extracted(("the user", "connects to", "Lab Cluster Example")), existing, memory,
        _settings(memory), now_date="2026-09-22", name_to_id={"lab cluster example": "lab-cluster-example"})
    assert _pairs(memory, "robert-example") == [("robert-example", "lab-cluster-example")]
    assert _pairs(memory, "bob-example") == []


# --- counted, logged as counts, the seam (R-CS3, R-CS4) -----------------------------


def test_a_page_less_claim_is_logged_as_a_count_and_never_as_text(tmp_path):
    memory = _bank(tmp_path)
    lines: list[str] = []
    sink = logger.add(lambda m: lines.append(str(m)), level="DEBUG",
                      filter=lambda r: r["name"] == "api.services.claim_pipeline")
    try:
        result = claim_pipeline.run_claim_pipeline(
            _extracted(("Zed Unknown", "uses", "Alpha Project")), [], memory, _settings(memory),
            now_date="2026-09-22", name_to_id={})
    finally:
        logger.remove(sink)
    assert result["claims_page_less"] == 1
    joined = "\n".join(lines)
    assert "1 claim(s) on 1 subject(s) without a page" in joined
    for needle in ("Zed Unknown", "zed-unknown", "Alpha Project", "alpha-project"):
        assert needle not in joined


def test_the_r_pj17_seam_is_asked_holds_nothing_and_writes_nothing(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    assert claim_pipeline.hold_page_less("zed-unknown", [], memory) == 0
    asked: list[tuple[str, int]] = []
    real = claim_pipeline.hold_page_less
    monkeypatch.setattr(claim_pipeline, "hold_page_less",
                        lambda s, c, m: asked.append((s, len(c))) or real(s, c, m))
    before = sorted(p.relative_to(memory).as_posix() for p in memory.rglob("*") if p.is_file())
    result = claim_pipeline.run_claim_pipeline(
        _extracted(("Zed Unknown", "uses", "Alpha Project")), [], memory, _settings(memory),
        now_date="2026-09-22", name_to_id={})
    assert asked == [("zed-unknown", 1)] and result["claims_page_less"] == 1
    after = sorted(p.relative_to(memory).as_posix() for p in memory.rglob("*") if p.is_file())
    assert after == before


def test_the_false_re_emitted_comment_is_gone():
    text = (REPO / "api" / "services" / "claim_pipeline.py").read_text(encoding="utf-8")
    assert "re-emitted next cycle" not in text
    assert "waits for its subject to be promoted" not in text


# --- wired into Sleep ---------------------------------------------------------------


def test_the_live_cycle_threads_the_map_and_counts_page_less_claims(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    markdown_parser.write(memory / "episodes" / f"{EP}.md",
                          {"id": EP, "processed": False, "source": "mcp", "timestamp": TS},
                          "user: Hana connects to Lab Cluster Example. Zed Unknown uses it too.")
    _page(memory, "hana-example", "Hana Example")
    _page(memory, "lab-cluster-example", "Lab Cluster Example", kind="tool")
    extracted = _extracted(("Hana", "connects to", "Lab Cluster Example"),
                           ("Zed Unknown", "uses", "Lab Cluster Example"))

    async def fake_extract(episodes, settings, **_kw):
        return extracted

    async def fake_resolve(extracted_arg, existing, settings, **_kw):
        return {"changes": [], "relationships": [], "episode_cooccurrences": {},
                "name_to_id": {"hana": "hana-example", "lab cluster example": "lab-cluster-example"}}

    async def fake_detect(changes, existing, settings, **kw):
        return []

    async def fake_resolve_and_prune(resolved, existing, settings):
        return list(resolved)

    async def fake_commit(memory_path, message):
        return None

    async def fake_porcelain(memory_path):
        return ""

    class _FakeIndexer:
        def __init__(self, *_a, **_k):
            pass

        def index_entities(self):
            return 0

        def index_episodes(self):
            return 0

        def index_claims(self):
            return 0

    monkeypatch.setattr("api.services.entity_extractor.extract", fake_extract)
    monkeypatch.setattr("api.services.entity_resolver.resolve", fake_resolve)
    monkeypatch.setattr("api.services.skill_extractor.detect_patterns", fake_detect)
    monkeypatch.setattr("api.services.conflict_resolver.resolve_and_prune", fake_resolve_and_prune)
    monkeypatch.setattr(git_service, "commit_changes", fake_commit)
    monkeypatch.setattr(git_service, "porcelain_status", fake_porcelain)
    monkeypatch.setattr("api.services.vector_index.SqliteVecIndexer", _FakeIndexer)

    asyncio.run(sleep_cycle.run(_settings(memory), cycle_id="pj0_test"))

    assert _pairs(memory, "hana-example") == [("hana-example", "lab-cluster-example")]
    state = sleep_cycle.get_sleep_state()
    assert (state.claims_page_less, state.subjects_page_less) == (1, 1)


def test_the_sleep_run_row_carries_the_page_less_counts(tmp_path, monkeypatch):
    events: list = []

    async def fake_status(_path):
        return ""

    async def fake_commit(_path, _message):
        return "abc1234"

    monkeypatch.setattr(git_service, "porcelain_status", fake_status)
    monkeypatch.setattr(git_service, "commit_changes", fake_commit)
    monkeypatch.setattr(telemetry, "record", events.append)
    monkeypatch.setattr(sleep_cycle._state, "claims_page_less", 3)
    monkeypatch.setattr(sleep_cycle._state, "subjects_page_less", 2)
    asyncio.run(sleep_cycle._finalize(
        tmp_path, "sleep_1", [], Settings(llm_mode="agent"),
        engine="claude-cli", connection="claude-plan", billing="subscription", authors=["claude-sonnet-5"],
    ))
    (row,) = [e for e in events if e.kind == "sleep_run"]
    assert row.refs["claims_page_less"] == 3 and row.refs["subjects_page_less"] == 2
```

Run: `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_claim_pipeline_subjects.py -q -p no:cacheprovider`
→ collection succeeds (the file imports only modules that exist), and every test fails on a missing name:
`AttributeError` for `endpoint_id` / `hold_page_less` / `SleepState.claims_page_less`, `TypeError` for
`name_to_id=`, `KeyError` for `result["name_to_id"]` / `result["claims_page_less"]`, and the false-comment test on
the comment itself. That is the red. Everything runs against tmp banks, so nothing outside `tmp_path` is touched.

- [ ] **Step 2: `entity_resolver.py`.** Insert above `async def resolve(` (`:20`):

```python
def endpoint_id(name: str, name_to_id: dict[str, str]) -> str | None:
    """The id Stage 2 resolved ``name`` to, or ``None`` — the edge rule, as one function.

    Exact (lower-cased) first, then the first ``fuzz.ratio > 85`` over
    ``name_to_id`` in insertion order, exactly as the relationship loop in
    :func:`resolve` always did inline. G141 PJ-0 (R-PJ17) made it a function so
    Sleep's claims key their subject and object through the SAME rule as the
    edge between them: a claim used to be keyed by ``sanitize_id(raw name)``,
    so a short name Stage 2 had matched ("Hana" → ``hana-example``) keyed a
    page that did not exist, and the claim was dropped while its edge landed.
    """
    key = (name or "").lower()
    hit = name_to_id.get(key)
    if hit:
        return hit
    for known_name, known_id in name_to_id.items():
        if fuzz.ratio(key, known_name) > 85:
            return known_id
    return None
```

In the relationship loop, replace

```python
        source_name = rel.get("source", "").lower()
        target_name = rel.get("target", "").lower()
        label = rel.get("label", "related to")

        source_id = name_to_id.get(source_name)
        target_id = name_to_id.get(target_name)

        # Also try fuzzy match for relationship endpoints
        if not source_id:
            for known_name, known_id in name_to_id.items():
                if fuzz.ratio(source_name, known_name) > 85:
                    source_id = known_id
                    break
        if not target_id:
            for known_name, known_id in name_to_id.items():
                if fuzz.ratio(target_name, known_name) > 85:
                    target_id = known_id
                    break
```

with

```python
        label = rel.get("label", "related to")
        # Exact, then fuzzy — one rule, shared with Sleep's claims (G141 PJ-0).
        source_id = endpoint_id(rel.get("source", ""), name_to_id)
        target_id = endpoint_id(rel.get("target", ""), name_to_id)
```

and the final return with

```python
    return {
        "changes": resolved,
        "relationships": resolved_edges,
        "episode_cooccurrences": episode_cooccurrences,
        # G141 PJ-0 (R-PJ17): the map the edges above resolved through, so
        # Stage 5.56's claims land on the same pages (`claim_pipeline`).
        "name_to_id": dict(name_to_id),
    }
```

- [ ] **Step 3: `entity_extractor.entities_to_claims`.** Change the signature and the two keying lines:

```python
def entities_to_claims(
    extracted: list[dict], memory_path: Path | None, *, resolve_id: Callable[[str], str] | None = None,
) -> list:
```

Add this paragraph at the end of its docstring:

```
    ``resolve_id`` (G141 PJ-0, R-CS1) maps an endpoint's raw name to a page id:
    Sleep passes ``claim_pipeline.subject_resolver`` over Stage 2's own
    ``name_to_id``, so a claim lands on the page its edge does. Without it the
    id is ``sanitize_id(name)`` — the pre-PJ-0 key every hermetic caller keeps.
```

After `from api.services.id_utils import sanitize_id` (`:515`), add `to_id = resolve_id or sanitize_id`. Then
replace `subject = sanitize_id(source)` / `obj = sanitize_id(target)` (`:530-531`) with
`subject = to_id(source)` / `obj = to_id(target)`. `Callable` is already imported (`:7`).

- [ ] **Step 4: `claim_pipeline.py`.** In the module docstring, replace

```
   verbatim (round-trip invariant). Subjects without an entity page are skipped
   (never raised) — the legacy promotion model owns page creation; a page-less
   claim simply waits for its subject to be promoted.
```

with

```
   verbatim (round-trip invariant). Each endpoint is keyed through Stage 2's
   ``name_to_id`` (G141 PJ-0), so a claim lands on the page its edge does, and
   "the user" lands on the ``owner: true`` page. A subject that still has no
   page is NOT written — the promotion model owns page creation — and its
   claims are counted (``claims_page_less``): this cycle marks the episode
   processed, so nothing re-extracts them. Holding them until the subject is
   promoted was ruled yes (G141 DECIDE (c), 2026-09-23) and is slice PJ-0b,
   which fills :func:`hold_page_less`.
```

Replace the import block `:42-50` with

```python
from datetime import date
from pathlib import Path
from typing import Callable

from loguru import logger

from api.services import markdown_parser, owner_identity, telemetry
from api.services.claim_reconciler import reconcile_stage3
from api.services.claims import Claim, parse_claims, write_claims
from api.services.entity_extractor import entities_to_claims
from api.services.entity_resolver import endpoint_id
from api.services.id_utils import sanitize_id

#: What Stage 1 writes for an endpoint that IS the person — its prompt speaks of
#: "the user" (``entity_extractor.EXTRACTION_SYSTEM_PROMPT``). Closed on purpose
#: (R-PJ17, R-CS2): only these, only onto a page marked ``owner: true``;
#: whatever still misses is counted, and G141's M3 reads the count.
OWNER_SURFACES = frozenset({"user", "the user", "me", "myself", "i"})


def _owner_page_id(existing_entities: list[dict] | None, memory_path: Path, settings) -> str | None:
    """The bank's ``owner: true`` page among Stage 2's ``existing`` list, or ``None``.

    Two owner pages can exist (G117 R3's disclosed gap: re-onboarding under a
    new display name writes a second page); the one ``owner_identity`` resolves
    wins, else the first by id, so the answer never depends on file order."""
    owners = sorted(
        str(e.get("id")) for e in (existing_entities or [])
        if isinstance(e, dict) and e.get("id") and (e.get("frontmatter") or {}).get("owner")
    )
    if len(owners) <= 1:
        return owners[0] if owners else None
    try:
        resolved = owner_identity.resolve_observer(memory_path, settings)
    except Exception:  # noqa: BLE001 - a tie-break is never worth a failed cycle
        resolved = None
    return resolved if resolved in owners else owners[0]


def subject_resolver(name_to_id: dict[str, str] | None, owner_id: str | None) -> Callable[[str], str]:
    """G141 PJ-0 (R-PJ17, R-CS1): the page id a claim endpoint's raw name keys to.

    The owner surfaces first (only when an owner page exists), then Stage 2's
    own map through ``entity_resolver.endpoint_id`` — the rule its edges use —
    then ``sanitize_id``, the pre-PJ-0 key. Stage 2's decisions carry over
    whole, its fuzzy merges included (R-CS5)."""
    table = dict(name_to_id or {})

    def resolve(name: str) -> str:
        key = (name or "").strip().lower()
        if owner_id and key in OWNER_SURFACES:
            return owner_id
        return endpoint_id(key, table) or sanitize_id(name)

    return resolve


def hold_page_less(subject: str, claims: list[Claim], memory_path: Path) -> int:
    """R-PJ17 SEAM, filled by slice PJ-0b. The owner ruled (G141 DECIDE (c),
    2026-09-23) that Sleep holds an unpromoted subject's claims beside its
    pending entity and writes them when it is promoted. That changes the
    pending store, so it is its own slice and not built in PJ-0.
    Returns how many of ``claims`` were held — always 0 until PJ-0b; the
    pipeline counts the rest as ``claims_page_less``. PJ-0b changes this body
    (and the pending store) and nothing else in the pipeline."""
    return 0
```

In `run_claim_pipeline`, add the keyword `name_to_id: dict[str, str] | None = None` after `extra_claims`.
Replace the `existing_entities` line of the Args docstring with

```
        existing_entities: Stage 2's ``existing`` list — read for the
            ``owner: true`` page "the user" maps onto (G141 PJ-0). Write-back
            still re-reads pages from disk, to see the entity path's fresh writes.
```

and add this Args entry:

```
        name_to_id: Stage 2's ``resolve(...)["name_to_id"]`` — every endpoint is
            keyed through it (R-CS1). ``None`` keeps ``sanitize_id``.
```

Replace the "Returns" paragraph with:

```
    Returns a dict: ``{"nudges": [...], "audit": [...], "claims_written": int,
    "subjects_written": int, "subjects_skipped": int, "claims_page_less": int,
    "page_less_subjects": [ids]}`` — the last two in memory only (R-CS3: a
    subject id is a slug of a name, so it is never logged). Never raises on a
    missing subject page.
```

Replace the Stage-1 emission line (`:107`) with

```python
    owner_id = _owner_page_id(existing_entities, memory_path, settings)
    incoming: list[Claim] = entities_to_claims(
        extracted, memory_path, resolve_id=subject_resolver(name_to_id, owner_id))
```

Replace the Stage-5 block, from `entities_dir = memory_path / "entities"` through the end of the function, with

```python
    entities_dir = memory_path / "entities"
    claims_written = 0
    subjects_written = 0
    subjects_skipped = 0
    claims_page_less = 0
    page_less_subjects: list[str] = []
    page_less_claim_ids: list[str] = []
    for subject, claims in reconciled.items():
        if not claims:
            continue
        filepath = entities_dir / f"{subject}.md"
        if not filepath.exists():
            # G141 PJ-0: not written — the promotion model owns page creation —
            # and not re-emitted either: this cycle marks the episode processed
            # (`sleep_cycle._mark_episodes_processed`), so nothing brings the
            # claim back. Count it and offer it to the R-PJ17 seam (PJ-0b).
            held = hold_page_less(subject, claims, memory_path)
            subjects_skipped += 1
            claims_page_less += len(claims) - held
            page_less_subjects.append(subject)
            page_less_claim_ids.extend(c.id for c in claims)
            continue
        try:
            parsed = markdown_parser.parse(filepath)
            # strict guard: if the existing block is unparseable, raise (caught
            # below) instead of overwriting claims we could not read.
            parse_claims(parsed.body, strict=True)
            new_body = write_claims(parsed.body, claims)
            if new_body != parsed.body:
                markdown_parser.write(filepath, parsed.frontmatter, new_body)
            subjects_written += 1
            claims_written += len(claims)
        except Exception as e:  # never let a single bad page abort the cycle
            logger.warning(
                f"claim write-back skipped for {subject}: {type(e).__name__}: {e}"
            )

    logger.info(
        f"Claim pipeline: {len(incoming)} emitted, "
        f"{subjects_written} pages written ({claims_written} claims), "
        f"{claims_page_less} claim(s) on {subjects_skipped} subject(s) without a page not written, "
        f"{len(nudges)} claim nudges"
    )
    if page_less_claim_ids:
        # R-CS3: opaque claim ids only — never the subject, a slug of a name.
        logger.debug(f"Claim pipeline: page-less claim ids {sorted(page_less_claim_ids)}")

    return {
        "nudges": nudges,
        "audit": audit,
        "claims_written": claims_written,
        "subjects_written": subjects_written,
        "subjects_skipped": subjects_skipped,
        "claims_page_less": claims_page_less,
        "page_less_subjects": sorted(page_less_subjects),
    }
```

(The `claim write-back skipped for {subject}` warning is the pre-existing line, byte-identical. It fires only
for a page that exists, and it is not this slice's to change.)

- [ ] **Step 5: `sleep_cycle.py`.** After `organic_resolutions: int = 0` (`:56`), add

```python
    # G141 PJ-0 (R-CS3): claims Stage 5.56 could not write because their
    # subject has no page, and how many subjects they were on. Counts only —
    # G141's M3 measure, carried into the `sleep_run` ledger row; never on
    # `/sleep/status`.
    claims_page_less: int = 0
    subjects_page_less: int = 0
```

After `_state.organic_resolutions = 0` in `run()` (`:951`), add `_state.claims_page_less = 0` and
`_state.subjects_page_less = 0`.

Replace `claim_result = run_claim_pipeline(extracted, existing, memory_path, settings)` (`:1298`) with

```python
        claim_result = run_claim_pipeline(
            extracted, existing, memory_path, settings,
            # G141 PJ-0: Stage 2's own map, so a claim lands where its edge did.
            name_to_id=resolved_result.get("name_to_id"),
        )
        _state.claims_page_less = int(claim_result.get("claims_page_less", 0) or 0)
        _state.subjects_page_less = int(claim_result.get("subjects_skipped", 0) or 0)
```

In the 5.56 log (`:1326`), replace `f"({claim_result.get('subjects_skipped', 0)} page-less), "` with

```python
            f"({claim_result.get('claims_page_less', 0)} claim(s) on "
            f"{claim_result.get('subjects_skipped', 0)} page-less subject(s) not written), "
```

In the `sleep_run` refs, after `"session_count": len(sessions or []),` (`:2017`), add

```python
            # G141 PJ-0 (R-CS3): M3's per-cycle page-less count — integers only.
            "claims_page_less": _state.claims_page_less,
            "subjects_page_less": _state.subjects_page_less,
```

- [ ] **Step 6: Green.** Run the new file, then the neighbours, then the whole suite:

```
cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_claim_pipeline_subjects.py api/tests/test_claim_pipeline.py api/tests/test_claim_emission.py api/tests/test_evidence_extraction.py api/tests/test_sleep_cycle_claims_wired.py api/tests/test_entity_resolver_transactional.py api/tests/test_claims_corruption_guard.py api/tests/test_claim_seeding.py -q -p no:cacheprovider
cd <worktree> && api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider
```

→ 0 failures.

- [ ] **Step 7: Commit.** Stage `api/services/entity_resolver.py`, `api/services/entity_extractor.py`,
  `api/services/claim_pipeline.py`, `api/services/sleep_cycle.py` and
  `api/tests/test_claim_pipeline_subjects.py`. Message:
  `fix(G141 PJ-0): Sleep keys claims through Stage 2's ids and counts page-less drops`. The body gets one line
  each for R-CS1..R-CS5, then the attribution lines.

---

### Task 2: PJ-4: the Stop hook writes per-turn times (R-PJ16)

**Files:**
- Modify: `api/services/transcript_capture.py`: the docstring `:16-22`, the imports `:35`, new helpers after
  `_body` (`:137`), the create path `:249-266` and the update path `:278-289`.
- Modify (docstrings only):
  - `api/services/episode_staging.py:22-26` (module) and `:207-210` (`stamps_for`);
  - `api/services/evidence.py:399-408` (`turn_stamps`).
- Modify: `api/tests/test_capture_transcript.py:132,164`.
- Modify: `CLAUDE.md:181-183`, `:346-348` and `:841-842`.
- Test: `api/tests/test_transcript_turn_stamps.py` (new).

**Interfaces:**
- Produces `transcript_capture._turn_sidecar(conv, body) -> list[dict]` and
  `transcript_capture._place_turns(fm, sidecar) -> None`.
- A Stop-hook episode's `turns` is a list of `{offset, ts, speaker}`, the last key.
- Consumes `episode_staging.EpisodeDraft`, `episode_staging.Turn`, `episode_staging.stamps_for`,
  `episode_staging.MAX_TURN_STAMPS` and `episode_staging.TURN_STAMP_KEYS`, plus `evidence.turn_starts`,
  `evidence.turn_stamps` and `evidence.turn_at`.

- [ ] **Step 1: Failing tests.** Create `api/tests/test_transcript_turn_stamps.py`:

```python
"""G141 PJ-4 (R-PJ16, R-CS6..R-CS9): the Stop hook writes G118's per-turn
sidecar ``turns: [{offset, ts, speaker}]`` instead of a count, so a Claude Code
turn is dated by its own time and a resumed session's day-3 turn reads day 3.
Synthetic transcripts only."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from api.services import episode_staging, evidence, markdown_parser, transcript_capture as tc

SID = "33333333-2222-4333-8444-555555555555"
REPO = Path(__file__).resolve().parents[2]
D1, D3 = "2026-09-03T10:00:00.000Z", "2026-09-05T08:30:00.000Z"


def _line(role: str, text: str, ts: str) -> str:
    content = text if role == "user" else [{"type": "text", "text": text}]
    return json.dumps({"type": role, "uuid": "u", "timestamp": ts, "sessionId": SID,
                       "cwd": "/home/example/alpha-project", "message": {"role": role, "content": content}})


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


def _capture(memory: Path, transcript: Path, turns: list[tuple[str, str, str]]) -> tuple[dict, str]:
    transcript.write_text("\n".join(_line(*t) for t in turns) + "\n", encoding="utf-8")
    r = tc.capture_transcript(memory, harness="claude-code", session_id=SID, transcript_path=str(transcript),
                              cwd="/home/example/alpha-project", keep_assistant=True)
    assert r.status in ("created", "updated"), r
    parsed = markdown_parser.parse(memory / "episodes" / f"{r.episode_id}.md")
    return dict(parsed.frontmatter), parsed.body


def test_a_capture_writes_the_sidecar_shape_last_and_outside_the_hash(memory, transcript):
    fm, body = _capture(memory, transcript, [("user", "Q1 about alpha-project", D1), ("assistant", "A1", D1)])
    assert list(fm)[-1] == "turns"
    assert fm["turns"] == [
        {"offset": 0, "ts": "2026-09-03T10:00:00+00:00", "speaker": "user"},
        {"offset": len("user: Q1 about alpha-project") + 1, "ts": "2026-09-03T10:00:00+00:00",
         "speaker": "assistant"},
    ]
    assert all(tuple(e) == episode_staging.TURN_STAMP_KEYS for e in fm["turns"])
    assert fm["content_hash"] == hashlib.sha256(body.encode()).hexdigest()[:12]  # the body alone


def test_offsets_are_turn_starts_over_the_hooks_own_body(memory, transcript):
    # A person's message can hold a line that only LOOKS like a turn marker.
    question = "Plan:\nassistant: this line is part of the question"
    fm, body = _capture(memory, transcript, [("user", question, D1), ("assistant", "A1", D1)])
    offsets = [e["offset"] for e in fm["turns"]]
    assert offsets == [0, len(f"user: {question}") + 1]  # the rendering's own line starts
    assert set(offsets) < set(evidence.turn_starts(body))  # each one a turn start the reader finds
    quoted = body.index("assistant: this line")
    assert evidence.turn_at(body, quoted, evidence.turn_stamps(fm))["ts"] is None  # never an inferred time


def test_a_grown_session_keeps_a_head_stable_list(memory, transcript):
    first, _ = _capture(memory, transcript, [("user", "Q1", D1), ("assistant", "A1", D1)])
    second, _ = _capture(memory, transcript, [("user", "Q1", D1), ("assistant", "A1", D1),
                                              ("user", "Q2", D3), ("assistant", "A2", D3)])
    assert second["turns"][:2] == first["turns"]
    assert len(second["turns"]) == 4 and list(second)[-1] == "turns"
    assert second["processed"] is False


def test_a_resumed_sessions_day_three_turn_anchors_to_day_three(memory, transcript):
    fm, body = _capture(memory, transcript, [
        ("user", "Started the rover arm plan", D1), ("assistant", "Noted.", D1),
        ("user", "Day three: connecting to lab-cluster-example now", D3), ("assistant", "Good luck.", D3),
    ])
    assert fm["timestamp"].startswith("2026-09-03")  # the session's start, unchanged (R-CS8)
    stamps = evidence.turn_stamps(fm)
    assert evidence.turn_at(body, body.index("Day three"), stamps)["ts"].startswith("2026-09-05")
    assert evidence.turn_at(body, body.index("Started"), stamps)["ts"].startswith("2026-09-03")


def test_a_turn_past_the_cap_has_no_stamp(memory, transcript):
    n = episode_staging.MAX_TURN_STAMPS + 1
    fm, body = _capture(memory, transcript, [("user", f"q{i:04d}", D1) for i in range(1, n + 1)])
    assert len(fm["turns"]) == episode_staging.MAX_TURN_STAMPS == 500
    hit = evidence.turn_at(body, body.index(f"q{n:04d}"), evidence.turn_stamps(fm))
    # R-CS9: nothing stored, so PJ-3's resolver falls back to the episode (basis `episode`).
    assert hit["number"] == n and hit["ts"] is None
    assert fm["timestamp"].startswith("2026-09-03")


def test_an_integer_count_episode_still_reads_as_no_stamps(memory):
    legacy = memory / "episodes" / "ep_2026-09-01_001.md"
    markdown_parser.write(legacy, {"id": "ep_2026-09-01_001", "timestamp": "2026-09-01T09:00:00+00:00",
                                   "capture_kind": "transcript", "session_id": "other", "turns": 2},
                          "user: Q\nassistant: A")
    fm = markdown_parser.parse(legacy).frontmatter
    assert evidence.turn_stamps(fm) == {}
    assert evidence.turn_at("user: Q\nassistant: A", 0, evidence.turn_stamps(fm)) is None


def test_a_legacy_count_becomes_the_list_on_the_sessions_next_rewrite(memory, transcript):
    fm, _ = _capture(memory, transcript, [("user", "Q1", D1)])
    path = memory / "episodes" / f"{fm['id']}.md"
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, {**parsed.frontmatter, "turns": 1}, parsed.body)  # the pre-PJ-4 shape
    grown, _ = _capture(memory, transcript, [("user", "Q1", D1), ("assistant", "A1", D1)])
    assert isinstance(grown["turns"], list) and len(grown["turns"]) == 2


def test_the_turns_key_has_one_shape_owner_and_one_reader():
    """R-PJ16 re-grepped (R-CS7): nothing reads a count. A reader that ever
    needs one gets `turn_count:`, never a second meaning for `turns`."""
    found: set[str] = set()
    for root in (REPO / "api", REPO / "mcp"):
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in {".venv", "tests", "__pycache__"}]
            for name in filenames:
                if name.endswith(".py"):
                    text = (Path(dirpath) / name).read_text(encoding="utf-8")
                    if '"turns"' in text or "'turns'" in text:
                        found.add(name)
    assert found == {"episode_staging.py", "evidence.py", "transcript_capture.py"}
```

Run it → the shape assertions fail (`fm["turns"]` is an int). That is the red. Two tests already pass and must
stay green: `test_an_integer_count_episode_still_reads_as_no_stamps` and the `turns`-key lint, which pin what
exists today.

- [ ] **Step 2: `transcript_capture.py`.** Change the import line (`:35`) to
  `from api.services import episode_ids, episode_staging, markdown_parser, session_stats, telemetry`. In the
  module docstring, after the paragraph ending "`episode_ids` (G114). No LLM anywhere.", add

```
Each turn's own time rides in G118's sidecar ``turns: [{offset, ts, speaker}]``
(G141 PJ-4, R-PJ16), written by ``episode_staging.stamps_for`` — the body here
is that module's line shape byte for byte — outside the hash, the last key,
head-stable at 500. The episode ``timestamp`` stays the session's start, so a
session resumed over three days keeps one id while its day-3 turns read day 3.
```

After `_body` (`:137`), add

```python
def _turn_sidecar(conv: Conversation, body: str) -> list[dict]:
    """G141 PJ-4 (R-PJ16, R-CS6): the per-turn ``[{offset, ts, speaker}]``
    sidecar, in the ONE shape ``evidence.turn_stamps`` reads.

    :func:`_body` renders ``"{role}: {text}"`` lines joined by ``\\n`` — byte
    for byte ``episode_staging._line`` — so the stager's own ``stamps_for``
    builds it: one writer of the shape, its head-stable 500 cap, aware-UTC
    times, and ``[]`` rather than offsets into text the body does not hold.
    Before this the hook wrote ``turns: <count>`` and every Claude Code turn
    dated to the session's first day."""
    draft = episode_staging.EpisodeDraft(turns=[
        episode_staging.Turn(text=t.text, speaker=t.role, ts=t.ts) for t in conv.turns])
    return episode_staging.stamps_for(draft, body)


def _place_turns(fm: dict, sidecar: list[dict]) -> None:
    """The sidecar is the LAST key (R-PB4), replaced whole on every rewrite; a
    body with no timed turn drops the key rather than keep stale offsets — the
    stager's ``_apply_common`` rule. Never in ``content_hash``: a time never
    re-queues a session."""
    fm.pop("turns", None)
    if sidecar:
        fm["turns"] = sidecar
```

Create path: delete the line `"turns": len(conv.turns),` from the `fm` literal. After

```python
            if cwd:
                fm["project_dir"] = cwd
```

add `_place_turns(fm, _turn_sidecar(conv, body))`.

Update path: replace the comment line `# R3: same file, same id, same original timestamp; new body, re-queued.`
with these two comment lines (keep the two `processed_by` lines that follow it):

```python
        # R3: same file, same id, same original timestamp; new body, re-queued,
        # and the whole per-turn sidecar rewritten (G141 PJ-4, R-PJ16).
```

Delete `fm["turns"] = len(conv.turns)`. After

```python
        if cwd and not fm.get("project_dir"):
            fm["project_dir"] = cwd
```

add `_place_turns(fm, _turn_sidecar(conv, body))` (before `markdown_parser.write(existing, fm, body)`).

- [ ] **Step 3: Docstrings that described the count.**
  - `episode_staging.py`: the module docstring's `turns` bullet (`:22-26`) spells the key with RST double
    backticks and wraps across lines 23-25. Match the words, not the line breaks: replace "because the Stop
    hook's ``turns:`` is an integer count; the merge with G118 slice 2 kept ONE key — the hook's int reads as
    "no stamps" in ``turn_stamps``" with "because the Stop hook's ``turns:`` was an integer count (until G141
    PJ-4); the merge with G118 slice 2 kept ONE key — a pre-PJ-4 hook episode's int reads as "no stamps" in
    ``turn_stamps``", rewrapped to the file's width. In `stamps_for`, replace "For the router's compat wrappers, which take a body as given." with "For callers
    that hold a body as given: the router's compat wrappers, and the Stop hook's writer
    (`transcript_capture`, G141 PJ-4), whose `role: text` body is this module's line shape byte for byte."
  - `evidence.turn_stamps` (the docstring wraps across `:402-406`; match the words): replace the sentence
    "Written by ONE writer, ``episode_staging`` — the chat
    importer (through the router's compat wrappers) and every Local-sources draft (a watched folder, a Wispr
    Flow meeting or dictation day) — which IS the coordination contract. Tolerant by design: the Stop hook's
    ``turns: <count>`` (``transcript_capture``) is an int, not a sidecar, and reads as no stamps;" with
    "Written by ONE writer, ``episode_staging`` — the chat importer (through the router's compat wrappers),
    every Local-sources draft, and since G141 PJ-4 the Stop hook (through ``stamps_for``) — which IS the
    coordination contract. Tolerant by design: a Stop-hook episode written before PJ-4 holds
    ``turns: <count>``, an int that reads as no stamps;". The rest of the docstring is unchanged.

- [ ] **Step 4: Update the two pinned ints** in `api/tests/test_capture_transcript.py`:
  - `:132` ends `... and fm["processed"] is False and fm["turns"] == 2`. Change it to
    `... and fm["processed"] is False and [e["speaker"] for e in fm["turns"]] == ["user", "assistant"]`.
  - `:164` `assert fm2["turns"] == 3` becomes
    `assert [e["speaker"] for e in fm2["turns"]] == ["user", "assistant", "user"]`.

- [ ] **Step 5: CLAUDE.md, the owner-visible rail amendment (R-PJ16).** Replace (`:180-183`)

```
  tombstoned (`source_deleted_at`) and never unlinked. A multi-turn source records G118's per-turn
  sidecar `turns: [{offset, ts, speaker}, …]` (R-PB4: an entry only for a turn with a time, the last
  key, outside `content_hash`, capped head-stable at 500) — the one shape `evidence.turn_stamps`
  reads; the Stop hook's `turns:` stays its integer count and reads as no stamps.
```

with

```
  tombstoned (`source_deleted_at`) and never unlinked. A multi-turn source records G118's per-turn
  sidecar `turns: [{offset, ts, speaker}, …]` (R-PB4: an entry only for a turn with a time, the last
  key, outside `content_hash`, capped head-stable at 500) — the one shape `evidence.turn_stamps`
  reads. The Stop hook writes it too since G141 PJ-4 (R-PJ16): its `role: text` body is the stager's
  line shape, so `episode_staging.stamps_for` builds the list, and the episode `timestamp` stays the
  session's start while each turn carries its own time. A Stop-hook episode written before PJ-4 still
  holds an integer count, which reads as no stamps.
```

Replace (`:346-348` at the base, `:349-351` after the replacement above)

```
`turns: [{offset, ts, speaker}]` in frontmatter, written by `episode_staging` outside
`content_hash`; the Stop hook's `turns:` is still a count, and a reader treats any non-list as no
times.
```

with

```
`turns: [{offset, ts, speaker}]` in frontmatter, written by `episode_staging` outside
`content_hash`; the Stop hook writes the same list (G141 PJ-4), and a reader treats any non-list — an
older Stop-hook episode's count — as no times.
```

Replace (`:841-842` at the base, `:844-845` after the replacement above)

```
  `POST /intake/import`; its `turns` sidecar is a list on imported episodes and an **integer
  count** on Stop-hook episodes, so a reader checks the type.
```

with

```
  `POST /intake/import`; its `turns` sidecar is a list, as on Stop-hook episodes since G141 PJ-4 —
  only a Stop-hook episode written before PJ-4 holds an **integer count**, so a reader checks the type.
```

- [ ] **Step 6: The grep the brief asks for.** Run
  `cd <worktree> && grep -rn "[\"']turns[\"']" api mcp | grep "\.py:" | grep -v "/tests/"`. Expect ONLY:
  - `episode_staging.py`: `fm.pop("turns", None)` and `fm["turns"] = stamps`;
  - `evidence.py`: the `__all__` line and `.get("turns")`;
  - `transcript_capture.py`: the two lines in `_place_turns`.

  Quote the output in the task report as "no reader uses the integer".

- [ ] **Step 7: Green.**

```
cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_transcript_turn_stamps.py api/tests/test_capture_transcript.py api/tests/test_transcript_extract.py api/tests/test_capture_hook.py api/tests/test_intake_turns.py -q -p no:cacheprovider
cd <worktree> && api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider
```

→ 0 failures.

- [ ] **Step 8: Commit.** Stage `api/services/transcript_capture.py`, `api/services/episode_staging.py`,
  `api/services/evidence.py`, `api/tests/test_transcript_turn_stamps.py`,
  `api/tests/test_capture_transcript.py` and `CLAUDE.md`. Message:
  `feat(G141 PJ-4): the Stop hook writes per-turn times (R-PJ16)`. The body says that this amends the CLAUDE.md
  rail "the Stop hook's `turns:` stays its integer count", then gives the attribution lines.

---

### Task 3: The demo bank knows it is one; the Stop hook, MCP and Telegram never write a real capture into it

**Files:**
- Create: `api/services/demo_guard.py`.
- Modify: `api/services/demo_bank.py`: the imports `:36`, `populate` `:92-106`, `_commit_history` `:355-386`.
- Modify: `api/services/bank_registry.py`: the imports `:26-41`, `activate_bank` `:420-427`, and new
  `most_recent_real_bank`, `CaptureBank` and `capture_bank` after `activate_bank`.
- Modify: `api/services/transcript_capture.py`: the imports, the `CaptureResult.reason` comment `:121`, the
  `capture_transcript` docstring `:217-223`, and the top of its body `:224`.
- Modify: `api/routers/capture.py`: the imports `:21-27` and `capture_transcript_endpoint` `:148-184`.
- Modify: `api/hooks/capture.py:37-40` (docstring) and `:144-150`.
- Modify: `api/services/mcp_tools.py`: the imports `:37` and a new `_demo_refusal`. One check in each of
  `save_url` (`:273`, first statement), `record_watch` (`:370`, after its `memory_path` line `:383`),
  `write_claim` (`:867`, after `:894`), `retract_claim` (`:1020`, after `:1024`) and `save_episode` (`:1758`,
  after `:1764`).
- Modify: `api/remote/runtime.py:40` (import) and `:229-231` (gate).
- Modify: `api/services/telegram_capture.py:44` (import) and `:231-235` (gate).
- Test: `api/tests/test_demo_capture.py` (new).

**Interfaces:**
- Produces:
  - from `demo_guard`: `MANIFEST = "_bank.yaml"`, `DEMO_KIND`, `GENERATOR_EMAIL`, `REFUSAL`,
    `AGENT_REFUSAL`, `TELEGRAM_ACK`, `HOOK_REFUSAL`, `manifest_path(bank)`, `write_manifest(bank) -> Path`,
    `is_demo(bank) -> bool`;
  - from `bank_registry`: `most_recent_real_bank(root) -> str | None`,
    `CaptureBank(name, path, redirected_from)` and `capture_bank(root) -> CaptureBank | None`;
  - the registry record key `last_active_at`;
  - the `POST /capture/transcript` response keys `bank` and `redirectedFrom`;
  - the transcript refusal reason `demo_bank`;
  - the remote status `demo`.
- Consumes `bank_registry.load_registry`, `bank_dir` and `resolve_active_bank_path`, plus `catalog.WRITE_TOOLS`.

- [ ] **Step 1: Failing tests.** Create `api/tests/test_demo_capture.py`:

```python
"""G141 capture-side track (R-CS10..R-CS14): a demo bank knows it is one, and
capture never writes a real conversation into it — the Stop hook saves into the
real bank left most recently (or answers 409); the MCP write tools and Telegram
refuse in plain words. The generator still writes its own made-up episodes.
Synthetic banks and transcripts only."""
from __future__ import annotations

import asyncio
import io
import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from _stdio_server import stdio_server
from api import config, main
from api.hooks import capture as hook
from api.remote import catalog
from api.remote.runtime import RemoteRuntime
from api.services import (bank_registry, demo_bank, demo_guard, mcp_tools, telegram_capture, telemetry,
                          transcript_capture as tc)

SID = "44444444-2222-4333-8444-555555555555"


def _git(bank: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(bank), *args], check=True, capture_output=True, text=True).stdout


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    root.mkdir()
    return root


def _demo(root: Path) -> Path:
    """A registered demo bank, marked the way the generator marks it — without
    populate's few seconds of git, which one test below covers."""
    slug = bank_registry.create_bank(root, "demo")
    path = bank_registry.bank_dir(root, slug)
    demo_guard.write_manifest(path)
    return path


def _open_demo_without_stamps(root: Path) -> None:
    """A registry from before `last_active_at` existed: the demo is active and
    no bank carries a stamp."""
    reg = bank_registry.load_registry(root)
    reg["active"] = "demo"
    bank_registry.save_registry(root, reg)


def _loose_demo(tmp_path: Path) -> Path:
    bank = tmp_path / "loose-demo"
    bank_registry.scaffold_bank(bank, git_init=False)
    demo_guard.write_manifest(bank)
    return bank


def _files(bank: Path) -> set[str]:
    return {p.relative_to(bank).as_posix() for p in bank.rglob("*") if p.is_file() and ".git" not in p.parts}


def _episodes(bank: Path) -> list[str]:
    return sorted(p.name for p in (bank / "episodes").glob("ep_*.md"))


@pytest.fixture(autouse=True)
def _fresh_settings():
    yield
    config.get_settings.cache_clear()


def _client(root: Path, monkeypatch) -> TestClient:
    monkeypatch.delenv("CICADA_MEMORY_PATH", raising=False)
    monkeypatch.setenv("CICADA_MEMORY_ROOT", str(root))
    config.get_settings.cache_clear()
    return TestClient(main.app)


# --- the marker (R-CS10) -----------------------------------------------------------


def test_the_generator_marks_its_bank_first_and_versions_the_mark(tmp_path):
    bank = tmp_path / "demo"
    bank_registry.scaffold_bank(bank)
    demo_bank.populate(bank)
    assert demo_guard.is_demo(bank)
    assert len(_episodes(bank)) >= 40  # the guard never stops the generator (R-CS17)
    assert _git(bank, "ls-files", demo_guard.MANIFEST).strip() == demo_guard.MANIFEST
    message = _git(bank, "log", "--format=%B", "--", demo_guard.MANIFEST)
    assert message.startswith("Demo bank") and "Cicada-Author: cicada" in message


def test_a_demo_generated_before_the_manifest_is_still_recognised(tmp_path):
    bank = tmp_path / "old-demo"
    bank_registry.scaffold_bank(bank)
    _git(bank, "config", "user.email", demo_guard.GENERATOR_EMAIL)
    assert demo_guard.is_demo(bank)


def test_a_real_bank_is_never_a_demo_even_when_named_demo(tmp_path):
    root = _root(tmp_path)
    path = bank_registry.bank_dir(root, bank_registry.create_bank(root, "demo"))
    assert not demo_guard.is_demo(path)
    (path / demo_guard.MANIFEST).write_text("kind: [unclosed", encoding="utf-8")
    assert not demo_guard.is_demo(path)  # a malformed manifest never blocks a real bank
    assert not demo_guard.is_demo(None) and not demo_guard.is_demo(tmp_path / "missing")


# --- which real bank was open last (R-CS11) ----------------------------------------


def test_activating_a_bank_stamps_the_one_it_leaves(tmp_path):
    root = _root(tmp_path)
    bank_registry.create_bank(root, "work")
    bank_registry.activate_bank(root, "work")  # leaves default
    banks = bank_registry.load_registry(root)["banks"]
    stamp = banks["default"]["last_active_at"]
    assert stamp and "last_active_at" not in banks["work"]
    bank_registry.activate_bank(root, "work")  # re-activating stamps nothing
    banks = bank_registry.load_registry(root)["banks"]
    assert banks["default"]["last_active_at"] == stamp and "last_active_at" not in banks["work"]


def test_the_fallback_is_the_real_bank_left_most_recently(tmp_path):
    root = _root(tmp_path)
    bank_registry.create_bank(root, "work")
    _demo(root)
    bank_registry.activate_bank(root, "work")  # leaves default
    bank_registry.activate_bank(root, "demo")  # leaves work — the most recent real bank
    assert bank_registry.most_recent_real_bank(root) == "work"
    target = bank_registry.capture_bank(root)
    assert (target.name, target.path, target.redirected_from) == (
        "work", bank_registry.bank_dir(root, "work"), "demo")


def test_without_stamps_one_real_bank_is_the_answer_and_two_are_never_guessed(tmp_path):
    root = _root(tmp_path)
    _demo(root)
    _open_demo_without_stamps(root)
    assert bank_registry.most_recent_real_bank(root) == "default"
    bank_registry.create_bank(root, "work")
    assert bank_registry.most_recent_real_bank(root) is None
    assert bank_registry.capture_bank(root) is None


def test_a_real_active_bank_is_its_own_capture_target(tmp_path):
    root = _root(tmp_path)
    target = bank_registry.capture_bank(root)
    assert (target.name, target.path, target.redirected_from) == ("default", root, None)


# --- the Stop hook (R-CS12) ---------------------------------------------------------


@pytest.fixture
def transcript(tmp_path, monkeypatch):
    folder = tmp_path / "claude-projects" / "-home-example-alpha-project"
    folder.mkdir(parents=True)
    monkeypatch.setattr(tc, "harness_root", lambda h: folder.parent)
    monkeypatch.setattr(tc, "_episode_cache", {})
    path = folder / f"{SID}.jsonl"
    path.write_text(json.dumps({"type": "user", "uuid": "u", "timestamp": "2026-09-23T09:00:00.000Z",
                                "sessionId": SID,
                                "message": {"role": "user", "content": "Should alpha-project ship Friday?"}})
                    + "\n", encoding="utf-8")
    return path


def _post(client: TestClient, transcript: Path):
    return client.post("/capture/transcript", json={"harness": "claude-code", "session_id": SID,
                                                    "transcript_path": str(transcript)})


def test_the_stop_hook_saves_into_the_real_bank_left_last_while_the_demo_is_open(tmp_path, monkeypatch,
                                                                                    transcript):
    root = _root(tmp_path)
    bank_registry.create_bank(root, "work")
    demo = _demo(root)
    bank_registry.activate_bank(root, "work")
    bank_registry.activate_bank(root, "demo")
    r = _post(_client(root, monkeypatch), transcript)
    assert r.status_code == 200, r.text
    assert (r.json()["bank"], r.json()["redirectedFrom"]) == ("work", "demo")
    assert len(_episodes(bank_registry.bank_dir(root, "work"))) == 1
    assert _episodes(demo) == [] and _episodes(root) == []


def test_with_no_real_bank_to_choose_the_hook_gets_409_and_nothing_is_written(tmp_path, monkeypatch,
                                                                               transcript):
    monkeypatch.setenv("CICADA_TELEMETRY", "on")
    root = _root(tmp_path)
    bank_registry.create_bank(root, "work")
    demo = _demo(root)
    _open_demo_without_stamps(root)  # two real banks and no stamp: never guess
    r = _post(_client(root, monkeypatch), transcript)
    assert r.status_code == 409 and r.json()["detail"] == demo_guard.HOOK_REFUSAL
    for bank in (root, bank_registry.bank_dir(root, "work"), demo):
        assert _episodes(bank) == []
    (ev,) = [e for e in telemetry.read_events() if e.kind == "capture"]
    assert ev.refs["status"] == "refused" and ev.refs["reason"] == "demo_bank"


def test_a_real_active_bank_is_named_and_nothing_is_redirected(tmp_path, monkeypatch, transcript):
    root = _root(tmp_path)
    r = _post(_client(root, monkeypatch), transcript)
    assert r.status_code == 200, r.text
    assert (r.json()["bank"], r.json()["redirectedFrom"]) == ("default", None)
    assert len(_episodes(root)) == 1


def test_the_service_refuses_a_demo_path_before_it_validates_anything(tmp_path):
    r = tc.capture_transcript(_loose_demo(tmp_path), harness="claude-code", session_id=SID,
                              transcript_path=str(tmp_path / "never-read.jsonl"), cwd=None,
                              keep_assistant=True)
    assert (r.status, r.reason) == ("refused", "demo_bank")  # not "not_a_file": nothing was checked


def test_the_hook_log_names_the_bank_a_redirected_session_went_to(tmp_path):
    token = tmp_path / "api_token"
    token.write_text("tok-123")
    log = tmp_path / "logs" / "capture.log"

    def post(url, body, tok, timeout):
        return 200, json.dumps({"status": "created", "bank": "work", "redirectedFrom": "demo"})

    payload = {"session_id": SID, "transcript_path": f"/home/example/.claude/projects/x/{SID}.jsonl",
               "cwd": "/home/example/alpha-project", "hook_event_name": "Stop"}
    rc = hook.main(["--harness", "claude-code"], stdin=io.StringIO(json.dumps(payload)), environ={},
                   post=post, log_path=log, token_path=token)
    assert rc == 0
    assert "http 200 created into work (the demo memory is open)" in log.read_text(encoding="utf-8")


# --- MCP, stdio and remote (R-CS13) --------------------------------------------------


def _ctx(bank: Path) -> mcp_tools.ToolContext:
    return mcp_tools.ToolContext(memory_path=lambda: bank, session_id="ses_test", harness="claude-code")


WRITES = {
    "cicada_save_episode": lambda ctx: mcp_tools.save_episode(ctx, "Decided alpha-project ships Friday.", "T"),
    "cicada_save_url": lambda ctx: mcp_tools.save_url(ctx, "https://example.com/a", None),
    "cicada_record_watch": lambda ctx: mcp_tools.record_watch(ctx, "https://example.com/v", "A summary."),
    "cicada_write_claim": lambda ctx: mcp_tools.write_claim(ctx, "alpha-project", "uses", "tool-example-a",
                                                            None, None, None, None),
    "cicada_retract_claim": lambda ctx: mcp_tools.retract_claim(ctx, "alpha-project", "clm_x", "wrong"),
}


def test_the_write_table_is_the_remote_catalogs():
    assert set(WRITES) == set(catalog.WRITE_TOOLS)


@pytest.mark.parametrize("tool", sorted(WRITES))
def test_every_mcp_write_tool_refuses_a_demo_bank_and_writes_nothing(tmp_path, tool):
    bank = _loose_demo(tmp_path)
    before = _files(bank)
    assert WRITES[tool](_ctx(bank)) == demo_guard.AGENT_REFUSAL
    assert _files(bank) == before


def test_the_stdio_server_refuses_too(tmp_path, monkeypatch):
    server = stdio_server()
    bank = _loose_demo(tmp_path)
    monkeypatch.setattr(server, "get_memory_path", lambda: bank)
    assert server.handle_save_episode("Decided alpha-project ships Friday.", "T") == demo_guard.AGENT_REFUSAL
    assert _episodes(bank) == []


def test_a_remote_write_into_a_demo_bank_is_refused_with_its_own_status(tmp_path):
    bank = _loose_demo(tmp_path)
    runtime = RemoteRuntime(memory_path=lambda: bank, post=lambda p, d: {}, sleep_running=lambda: False)
    connector = catalog.Connector(id="ab12cd34", label="Phone", app="claude", scopes=catalog.DEFAULT_SCOPES,
                                  created_at="2026-09-01T00:00:00+00:00", last_client="claude-ai")
    text, status = runtime.call(connector, "cicada_save_episode", {"content": "x", "title": "t"})
    assert (text, status) == (demo_guard.AGENT_REFUSAL, "demo")


def test_a_real_bank_still_saves(tmp_path):
    bank = tmp_path / "real"
    (bank / "episodes").mkdir(parents=True)
    assert "Episode saved" in mcp_tools.save_episode(_ctx(bank), "Decided alpha-project ships Friday.", "T")


# --- Telegram (R-CS14) ------------------------------------------------------------


def test_a_telegram_message_is_not_saved_into_a_demo_bank_and_the_chat_is_told(tmp_path):
    bank = _loose_demo(tmp_path)
    calls: list = []

    def spy(*a, **k):
        calls.append(a)
        return {"status": "created"}

    update = {"update_id": 1, "message": {"message_id": 1, "from": {"id": 111, "is_bot": False,
                                                                    "first_name": "Bob"},
                                          "chat": {"id": 111, "type": "private"}, "date": 1_750_000_000,
                                          "text": "remember alpha-project https://example.com/a"}}
    result = asyncio.run(telegram_capture.ingest_telegram_update(bank, update, save_url_fn=spy,
                                                                 save_episode_fn=spy))
    assert result == {"kind": "skipped", "reason": "demo_bank", "ack": demo_guard.TELEGRAM_ACK, "chat_id": 111}
    assert calls == []
```

Run: `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_demo_capture.py -q -p no:cacheprovider`
→ collection fails (`api.services.demo_guard` does not exist). That is the red.

- [ ] **Step 2: Create `api/services/demo_guard.py`:**

```python
"""A demo bank is synthetic, and capture never writes a real conversation into it.

G117's demo bank (``demo_bank.populate``, ``POST /banks/demo``) exists so a new
person — and the README's screenshots (G90) — can try Cicada on made-up people
and projects. Every capture writer writes into the ACTIVE bank, so on
2026-09-23, while the demo was open for screenshots, a real Claude Code
session's Stop hook wrote that session INTO the demo bank and its words reached
demo content. The file was quarantined by hand; this module is the rule that
makes it impossible (G141 capture-side track, R-CS10..R-CS17).

One question, answered from the bank directory alone, so any writer that holds
only a bank path — the stdio MCP server, the Telegram webhook, a folder sync —
can ask it with one small read:

* ``<bank>/_bank.yaml`` saying ``kind: demo`` — written FIRST by
  ``demo_bank.populate`` and committed in the bank, so it travels with a
  duplicate, a rename, an export or a hand copy (R-CS10);
* for a demo bank generated before that file existed, the generator's own
  commit identity (:data:`GENERATOR_EMAIL`) in ``<bank>/.git/config`` — what
  ``demo_bank._commit_history`` has written since G117 — so an existing demo
  bank is recognised with no migration and no write.

Never the bank's NAME: a person may call a real bank "demo". Pure — pathlib,
re and yaml; ``bank_registry`` imports this module, never the reverse. A
malformed manifest reads as "not demo": a hand-made file must never block a
real bank's capture, and the git identity still catches every generated demo.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

MANIFEST = "_bank.yaml"
DEMO_KIND = "demo"
#: The demo generator's commit identity — its one trace in a bank made before
#: the manifest. `demo_bank._commit_history` spells it through this constant.
GENERATOR_EMAIL = "demo@cicada.example"
_GENERATOR_EMAIL_RE = re.compile(r"^\s*email\s*=\s*" + re.escape(GENERATOR_EMAIL) + r"\s*$", re.MULTILINE)

#: The 409 detail every HTTP capture route answers with (R-CS15), shown as-is in
#: the app's panels — so it is written for the person.
REFUSAL = ("Cicada has its demo memory open. It only holds made-up examples, so nothing real is saved "
           "into it. Switch back to your own memory, then try again.")
#: What an MCP write tool answers (R-CS13) — an agent relays it, so it says
#: what to tell the person.
AGENT_REFUSAL = ("Not saved: Cicada has its demo memory open, and the demo only holds made-up examples. "
                 "Tell the person to switch back to their own memory in Cicada, then save this again.")
#: Telegram's chat reply (R-CS14).
TELEGRAM_ACK = "Not saved — Cicada has its demo memory open. Switch back to your own memory and send it again."
#: The Stop hook's 409 when no real bank can be chosen (R-CS12). The hook logs it.
HOOK_REFUSAL = ("The demo memory is open and Cicada couldn't tell which of your own memories to save this "
                "session into, so nothing was saved. Switch back to your memory in Cicada — the next reply "
                "saves the whole session.")

_MANIFEST_TEXT = (
    "# Written by Cicada's demo generator (api/services/demo_bank.py). This bank holds only\n"
    "# made-up examples, so every capture writer refuses it (api/services/demo_guard.py).\n"
    f"kind: {DEMO_KIND}\n"
)


def manifest_path(bank_path: Path) -> Path:
    return Path(bank_path) / MANIFEST


def write_manifest(bank_path: Path) -> Path:
    """Mark ``bank_path`` as a demo bank. Only ``demo_bank.populate`` calls it."""
    path = manifest_path(bank_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_MANIFEST_TEXT, encoding="utf-8")
    return path


def is_demo(bank_path: Path | None) -> bool:
    """True when ``bank_path`` is a demo bank (R-CS10). Never raises."""
    if bank_path is None:
        return False
    bank = Path(bank_path)
    try:
        data = yaml.safe_load(manifest_path(bank).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        data = None
    if isinstance(data, dict) and data.get("kind") == DEMO_KIND:
        return True
    try:
        config = (bank / ".git" / "config").read_text(encoding="utf-8", errors="replace")
    except OSError:  # no git, or `.git` is a worktree/submodule file — not a generated demo
        return False
    return bool(_GENERATOR_EMAIL_RE.search(config))
```

- [ ] **Step 3: `demo_bank.py`.**
  - Add `demo_guard` to the `from api.services import …` line (`:36`).
  - In `populate`, make `demo_guard.write_manifest(bank_dir)` the first statement after
    `bank_dir = Path(bank_dir)`, and add this sentence to its docstring: "The bank is marked demo FIRST
    (`demo_guard.write_manifest`, G141 capture-side track R-CS10), so a populate that fails half-way still
    leaves a bank every capture writer refuses."
  - In `_commit_history`, replace the literal `"demo@cicada.example"` with `demo_guard.GENERATOR_EMAIL`.
  - Directly after the second `subprocess.run([... "config", "user.name", "Cicada Demo"], ...)`, insert

```python
    # R-CS10: the manifest is a fact about the bank, so it is versioned —
    # committed alone, first, as `cicada` (no model wrote it, no person's words
    # are in it). Untracked, the next `git add -A` would sweep it into a Sleep
    # commit under a model's name (the G85 smear).
    _run_commit(
        bank_dir,
        git_service.build_commit_message(
            "Demo bank",
            [f"{demo_guard.MANIFEST}: created (trigger: user/companion_app)"],
            authors=["cicada"],
        ),
        [demo_guard.MANIFEST],
    )
```

- [ ] **Step 4: `bank_registry.py`.**
  - Add `from dataclasses import dataclass` to the stdlib imports.
  - Change `from api.services import predicates` to `from api.services import demo_guard, predicates`.
  - Replace `activate_bank` with the version below, and add the three new definitions directly after it:

```python
def activate_bank(root: Path, name: str) -> None:
    """Point ``active`` at ``name``. Raises ``ValueError`` if unknown.

    Stamps ``last_active_at`` (aware UTC) on the bank being LEFT (G141
    capture-side track, R-CS11): the one record of which real bank was open
    most recently, which is where the Stop hook saves a session while the demo
    bank is open (:func:`capture_bank`). Re-activating the active bank stamps
    nothing; ``list_banks`` never reads the key, so ``/banks`` is unchanged.
    """
    root = Path(root)
    registry = _ensure_registry(root)
    banks = registry.get("banks", {}) or {}
    if name not in banks:
        raise ValueError(f"Unknown bank '{name}'")
    previous = registry.get("active")
    if previous and previous != name and isinstance(banks.get(previous), dict):
        banks[previous]["last_active_at"] = datetime.now(timezone.utc).isoformat()
    registry["active"] = name
    save_registry(root, registry)


def most_recent_real_bank(root: Path) -> str | None:
    """The real bank a capture falls back to while a demo bank is active (R-CS11).

    Among the registered banks that are not active, exist on disk and are not
    demo banks: the one LEFT most recently (``last_active_at``). A registry
    written before the stamp existed has none — then the only real bank is the
    answer when there is exactly one (the common install: the legacy
    ``default`` plus ``demo``), and ``None`` when there are several: Cicada
    never guesses which of two real memories a conversation belongs to.
    """
    root = Path(root)
    registry = load_registry(root)
    active = registry.get("active")
    candidates: list[tuple[str, str]] = []
    for name, record in (registry.get("banks", {}) or {}).items():
        if name == active:
            continue
        path = bank_dir(root, name)
        if not path.is_dir() or demo_guard.is_demo(path):
            continue
        stamp = str(record.get("last_active_at") or "") if isinstance(record, dict) else ""
        candidates.append((stamp, name))
    stamped = [c for c in candidates if c[0]]
    if stamped:
        return max(stamped)[1]
    return candidates[0][1] if len(candidates) == 1 else None


@dataclass(frozen=True)
class CaptureBank:
    """Where an unattended capture writes (R-CS12). ``redirected_from`` names
    the demo bank that was active when the capture was sent elsewhere."""

    name: str
    path: Path
    redirected_from: str | None = None


def capture_bank(root: Path) -> CaptureBank | None:
    """The active bank, unless it is a demo bank — then the real bank left most
    recently, or ``None`` when there is none to choose (R-CS12). Resolved per
    call from ``banks.yaml``, like every bank path (the split-brain rule)."""
    root = Path(root)
    registry = load_registry(root)
    active = str(registry.get("active") or DEFAULT_BANK)
    path = resolve_active_bank_path(root)
    if not demo_guard.is_demo(path):
        return CaptureBank(active, path)
    fallback = most_recent_real_bank(root)
    if fallback is None:
        return None
    return CaptureBank(fallback, bank_dir(root, fallback), redirected_from=active)
```

- [ ] **Step 5: `transcript_capture.py`.**
  - Change the import line to
    `from api.services import demo_guard, episode_ids, episode_staging, markdown_parser, session_stats, telemetry`.
  - Leave `TranscriptRefused` and its enum untouched: it is `validate_transcript_path`'s exception, and a demo
    bank is refused before validation runs. Instead:
    - change `CaptureResult`'s `reason: str | None = None` to
      `reason: str | None = None  # a TranscriptRefused enum, or "demo_bank" (G141 capture-side track)`;
    - in `capture_transcript`'s docstring, change "``refused`` (nothing read, nothing written)" to "``refused``
      (nothing read, nothing written — an unsafe path, or a demo bank, reason ``demo_bank``)".
  - Make this the first statement in `capture_transcript`'s body, before the `try:` that validates the path:

```python
    if demo_guard.is_demo(memory_path):
        # G141 capture-side track (R-CS12): a demo bank holds only made-up
        # examples, so a real session is never written into it — refused
        # before the transcript is even validated, and recorded like every
        # other refusal. The router sends the session to a real bank first;
        # this is the guard for any caller that does not.
        _record(harness, session_id, "refused", None, bank, "demo_bank")
        return CaptureResult("refused", None, 0, 0, {}, reason="demo_bank")
```

- [ ] **Step 6: `routers/capture.py`.**
  - Replace `from api.services import telemetry` (`:21`) with `from api.services import bank_registry, demo_guard`.
    `telemetry` had one use here, `bank_name`, which the body below replaces.
  - Add this paragraph at the end of `capture_transcript_endpoint`'s docstring:

```
    G141 capture-side track (R-CS12): the demo bank is never the target. While
    it is open, the session is saved into the real bank left most recently
    (``bank_registry.capture_bank``) and the response names it — ``bank`` and
    ``redirectedFrom`` — so the hook's log says where it went; with no real
    bank to choose, ``409`` and nothing is read. Every Stop re-captures the
    whole session, so the first reply after switching back saves it in full.
```

  - Replace the body from `result = await asyncio.to_thread(` to the end with

```python
    target = bank_registry.capture_bank(settings.memory_root)
    # No real bank to fall back to: the service is handed the demo path and
    # refuses it unread, so the refusal lands in the ledger like any other.
    memory_path = target.path if target is not None else settings.memory_path
    result = await asyncio.to_thread(
        capture_transcript,
        memory_path,
        harness=req.harness,
        session_id=req.session_id,
        transcript_path=req.transcript_path,
        cwd=req.cwd,
        keep_assistant=settings.capture_assistant_replies,
        bank=memory_path.name,
    )
    if target is None or result.status == "refused":
        if target is None or result.reason == "demo_bank":
            raise HTTPException(status_code=409, detail=demo_guard.HOOK_REFUSAL)
        raise HTTPException(status_code=400, detail=result.reason)
    if target.redirected_from:
        logger.info(f"capture: the demo bank is open — saved the {req.harness} session into '{target.name}'")
    return {
        "status": result.status,
        "episodeId": result.episode_id,
        "turnsUser": result.turns_user,
        "turnsAssistant": result.turns_assistant,
        "summary": result.summary,
        "bank": target.name,
        "redirectedFrom": target.redirected_from,
    }
```

- [ ] **Step 7: `api/hooks/capture.py`** stays stdlib-only. In the module docstring (the sentence wraps across
  `:38-39`; match the words), replace "the first 8 characters of the session id, and the outcome — never a
  path, never content." with "the first 8 characters
  of the session id, and the outcome — plus, when the demo memory was open, the name of the bank the session
  was saved into (G141 capture-side track) — never a path, never content." In `main`, replace

```python
        try:
            parsed = json.loads(text)
            outcome = str(parsed.get("status") or parsed.get("detail") or "")
        except (ValueError, AttributeError):
            pass
```

with

```python
        try:
            parsed = json.loads(text)
            outcome = str(parsed.get("status") or parsed.get("detail") or "")
            if parsed.get("redirectedFrom"):
                # R-CS12: the demo bank was open, so the backend saved this
                # session into a real bank — say which (a name, never a path).
                outcome += f" into {parsed.get('bank')} (the demo memory is open)"
        except (ValueError, AttributeError):
            pass
```

- [ ] **Step 8: `mcp_tools.py`.** Change `:37` to
  `from api.services import agent_commits, agentic_write, demo_guard, episode_ids, episode_scrub, search_service`.
  After the `ToolContext` class, add

```python
def _demo_refusal(memory_path: Path) -> str | None:
    """G141 capture-side track (R-CS13): every write tool refuses a demo bank —
    one check for stdio and remote alike. It takes the bank the tool already
    resolved for this call, so the check, the write, the ledger row and the
    commit all name ONE bank (the split-brain rule; `write_claim`'s "one bank
    resolution per call"). The demo holds only made-up examples; a real
    conversation's note or belief written into it leaks into the demo's
    content and its screenshots."""
    return demo_guard.AGENT_REFUSAL if demo_guard.is_demo(memory_path) else None
```

(`Path` is already imported at `:34`.) Insert the check in each of the five tools:

- In `write_claim`, `retract_claim`, `save_episode` and `record_watch`: directly after the tool's one
  `memory_path = ctx.memory_path()` line. In `save_episode` that is before `episodes_dir.mkdir(...)`; in
  `record_watch` it is after the URL check and before `watch_record.resolve(...)`; in `write_claim` it is before
  `author = ctx.author`.

```python
    if (refusal := _demo_refusal(memory_path)) is not None:
        return refusal
```

- In `save_url`, as the FIRST statement, before the URL is stripped: it resolves no bank before its backend
  path, and its backend-down path resolves its own later.

```python
    if (refusal := _demo_refusal(ctx.memory_path())) is not None:
        return refusal
```

- [ ] **Step 9: `api/remote/runtime.py`.** Change `:40` to
  `from api.services import demo_guard, handshake, mcp_tools, telemetry`. In `RemoteRuntime.call`, directly
  after the `busy` branch, add

```python
        elif tool in catalog.WRITE_TOOLS and demo_guard.is_demo(self._memory_path()):
            # R-CS13: its own status, so the `remote_call` row says why nothing was written.
            text, status = demo_guard.AGENT_REFUSAL, "demo"
```

- [ ] **Step 10: `telegram_capture.py`.** Change `:44` to
  `from api.services import demo_guard, episode_ids, episode_scrub, markdown_parser, owner_identity`. In
  `ingest_telegram_update`, directly after `captured_at = parsed["date"]` and before the `try:`, add

```python
    if demo_guard.is_demo(memory_path):
        # G141 capture-side track (R-CS14): a 200 with a reply, never an error —
        # Telegram retries a non-2xx for hours, and a retry landing after the
        # person switched back would save a message they were told was not saved.
        return {"kind": "skipped", "reason": "demo_bank", "ack": demo_guard.TELEGRAM_ACK, "chat_id": chat_id}
```

- [ ] **Step 11: Green.**

```
cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_demo_capture.py api/tests/test_demo_bank.py api/tests/test_banks.py api/tests/test_bank_trash_export.py api/tests/test_capture_transcript.py api/tests/test_capture_hook.py api/tests/test_telegram_capture.py api/tests/test_remote_runtime.py api/tests/test_mcp_stdio_golden.py api/tests/test_episode_writers_scrub.py api/tests/test_entity_provenance.py -q -p no:cacheprovider
cd <worktree> && api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider
```

→ 0 failures.

- [ ] **Step 12: Commit.** Stage `api/services/demo_guard.py`, `api/services/demo_bank.py`,
  `api/services/bank_registry.py`, `api/services/transcript_capture.py`, `api/routers/capture.py`,
  `api/hooks/capture.py`, `api/services/mcp_tools.py`, `api/remote/runtime.py`,
  `api/services/telegram_capture.py` and `api/tests/test_demo_capture.py`. Message:
  `fix(G117): the demo bank refuses real captures — the Stop hook saves into the last real bank`. The body
  cites R-CS10..R-CS14 and says that the other HTTP writers, the intake and Sleep's tail follow in the next
  commit, then gives the attribution lines.

---

### Task 4: Every other capture route, the intake's target and Sleep's tail refuse the demo bank

**Files:**
- Modify: `api/routers/capture.py`. Add `refuse_capture_into_demo` after `router = APIRouter()` (`:29`).
- Modify: `api/routers/sources.py`. Import it, add `_DEMO_GATE` after `router = APIRouter()` (`:51`), and
  gate 10 decorators: `:81`, `:169`, `:280`, `:363`, `:444`, `:767`, `:792`, `:815`, `:843` and `:861`.
- Modify: `api/routers/local_sources.py`. Import it and add `_DEMO_GATE`, then gate 5 decorators: `:41`,
  `:68`, `:91`, `:172` and `:183`.
- Modify: `api/routers/connectors.py`. Import it and gate the decorator at `:241`.
- Modify: `api/routers/intake.py:44` (import) and `resolve_target` `:356-368`.
- Modify: `api/services/sleep_cycle.py`, the tail's guarded branch `:884-889`.
- Modify: `CLAUDE.md`, the Awake rails (`:147` and after the last rail bullet, which ends at `:191`).
- Test: `api/tests/test_demo_capture_routes.py` (new).

**Interfaces:**
- Produces `api.routers.capture.refuse_capture_into_demo(settings=Depends(get_settings)) -> None`, which
  raises `HTTPException(409, demo_guard.REFUSAL)`.
- `intake.resolve_target` raises the same for a demo target.
- Consumes `demo_guard.is_demo` and `demo_guard.REFUSAL`.

- [ ] **Step 1: Failing tests.** Create `api/tests/test_demo_capture_routes.py`:

```python
"""G141 capture-side track (R-CS15, R-CS16): with the demo bank open, every
HTTP capture route answers 409 and writes nothing; the intake checks the bank
it writes INTO, so importing into your own memory still works; Sleep's tail on
a demo bank takes nothing in from outside. Synthetic banks only."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from _intake_fixtures import claude_conversations
from api import config, main
from api.routers.capture import refuse_capture_into_demo
from api.services import bank_registry, demo_guard, sleep_cycle

#: Every POST/PUT under /capture/ and /sources/ that the one dependency gates,
#: with a concrete path to call (R-CS15).
GATED = {
    ("POST", "/sources/save"): "/sources/save",
    ("POST", "/sources/upload"): "/sources/upload",
    ("POST", "/sources/rss"): "/sources/rss",
    ("POST", "/sources/sync-bookmarks"): "/sources/sync-bookmarks",
    ("POST", "/sources/sync-safari-tabs"): "/sources/sync-safari-tabs",
    ("POST", "/sources/feeds"): "/sources/feeds",
    ("POST", "/sources/poll-feeds"): "/sources/poll-feeds",
    ("POST", "/sources/calendars"): "/sources/calendars",
    ("POST", "/sources/poll-calendars"): "/sources/poll-calendars",
    ("POST", "/sources/sync-notes"): "/sources/sync-notes",
    ("POST", "/sources/folders"): "/sources/folders",
    ("PUT", "/sources/folders/{folder_id}"): "/sources/folders/f1",
    ("POST", "/sources/folders/{folder_id}/sync"): "/sources/folders/f1/sync",
    # A connector id no adapter has: were the gate missing, the handler 404s
    # before any adapter could reach the network (sync_now passes allow_fetch=True).
    ("POST", "/sources/connectors/{connector_id}/sync"): "/sources/connectors/no-such-connector/sync",
    ("POST", "/capture/local-source/wispr-flow"): "/capture/local-source/wispr-flow",
    ("PUT", "/capture/local-source/wispr-flow/settings"): "/capture/local-source/wispr-flow/settings",
}
#: The rest of the prefixes, each with the reason it is not the dependency's.
HANDLED_ELSEWHERE = {
    ("POST", "/capture/transcript"): "redirects to the real bank left last (test_demo_capture.py)",
    ("POST", "/capture/telegram"): "answers 200 with a reply so Telegram never retries (test_demo_capture.py)",
    ("POST", "/intake/import"): "checks its TARGET bank in intake.resolve_target",
    ("POST", "/intake/sniff"): "stages nothing; a chat export's TARGET bank is checked in intake.resolve_target",
    ("PUT", "/sources/connectors/{connector_id}/credentials"):
        "stores the secret in ~/.cicada/secrets.env; only restamps the bank's sync_state.json, no content",
    ("POST", "/sources/connectors/{connector_id}/authorize"): "returns a sign-in link, takes nothing in",
}
PREFIXES = ("/capture/", "/sources/", "/intake/")


@pytest.fixture(autouse=True)
def _no_local_reader(monkeypatch):
    """With no body, `/sources/sync-bookmarks` and `/sources/sync-notes` fall
    back to THIS machine's bookmark files and Notes.app (`sources.py:428,883`).
    A bodiless call that reaches a handler (this file's red phase, or a gate
    removed on purpose to prove the lint) must fail loudly, never read them."""
    from api.services import bookmark_sync, notes_sync

    def _refuse(*_a, **_k):
        raise AssertionError("a demo-gate test reached a local reader; the gate is missing")

    monkeypatch.setattr(bookmark_sync, "sync_from_local_files", _refuse)
    monkeypatch.setattr(notes_sync, "sync_from_local_notes", _refuse)


def _routes() -> dict[tuple[str, str], APIRoute]:
    return {(m, r.path): r for r in main.app.routes if isinstance(r, APIRoute) for m in r.methods}


def test_every_capture_route_is_gated_or_named():
    live = {k for k in _routes() if k[0] in ("POST", "PUT") and k[1].startswith(PREFIXES)}
    assert live == set(GATED) | set(HANDLED_ELSEWHERE)


def test_the_gated_routes_carry_the_one_dependency_and_the_others_do_not():
    routes = _routes()
    for key in GATED:
        assert refuse_capture_into_demo in {d.call for d in routes[key].dependant.dependencies}, key
    for key in HANDLED_ELSEWHERE:
        assert refuse_capture_into_demo not in {d.call for d in routes[key].dependant.dependencies}, key


@pytest.fixture
def demo_open(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    slug = bank_registry.create_bank(root, "demo")
    demo = bank_registry.bank_dir(root, slug)
    demo_guard.write_manifest(demo)
    bank_registry.activate_bank(root, slug)
    monkeypatch.delenv("CICADA_MEMORY_PATH", raising=False)
    monkeypatch.setenv("CICADA_MEMORY_ROOT", str(root))
    config.get_settings.cache_clear()
    yield SimpleNamespace(client=TestClient(main.app), root=root, demo=demo)
    config.get_settings.cache_clear()


def _files(path: Path) -> set[str]:
    return {p.relative_to(path).as_posix() for p in path.rglob("*") if p.is_file() and ".git" not in p.parts}


@pytest.mark.parametrize("key", sorted(GATED))
def test_a_gated_route_answers_409_and_writes_nothing(demo_open, key):
    before = _files(demo_open.demo)
    r = demo_open.client.request(key[0], GATED[key])
    assert r.status_code == 409, (key, r.text)
    assert r.json()["detail"] == demo_guard.REFUSAL
    assert _files(demo_open.demo) == before


def test_a_real_active_bank_is_not_refused(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.delenv("CICADA_MEMORY_PATH", raising=False)
    monkeypatch.setenv("CICADA_MEMORY_ROOT", str(root))
    config.get_settings.cache_clear()
    try:
        assert TestClient(main.app).post("/sources/poll-feeds").status_code == 200
    finally:
        config.get_settings.cache_clear()


def _export() -> bytes:
    return json.dumps(claude_conversations(1)).encode()


def test_importing_into_the_open_demo_is_refused_and_writes_nothing(demo_open):
    for route in ("/intake/import", "/intake/sniff", "/conversations/upload",
                  f"/banks/{demo_open.demo.name}/import"):
        r = demo_open.client.post(route, files={"file": ("conversations.json", _export(), "application/json")})
        assert r.status_code == 409 and r.json()["detail"] == demo_guard.REFUSAL, (route, r.text)
    assert list((demo_open.demo / "episodes").glob("*.md")) == []


def test_importing_into_your_own_memory_still_works_while_the_demo_is_open(demo_open):
    r = demo_open.client.post("/intake/import", params={"bank": "default"},
                              files={"file": ("conversations.json", _export(), "application/json")})
    assert r.status_code == 200, r.text
    assert r.json()["bank"] == "default" and r.json()["episodesStaged"] >= 1
    assert list((demo_open.root / "episodes").glob("ep_*.md"))
    assert list((demo_open.demo / "episodes").glob("*.md")) == []


# --- Sleep's tail (R-CS16) ---------------------------------------------------------

TAIL_STEPS = ("_refresh_state_safely", "_expire_claims_safely", "_poll_connectors_safely",
              "_poll_feeds_and_calendars_safely", "_backfill_links_safely", "_resolve_papers_safely",
              "_replay_wispr_todos_safely", "_warm_logos_safely", "_refresh_questions_safely")


def _tail_order(monkeypatch, bank: Path) -> list[str]:
    order: list[str] = []

    def fake(name):
        async def _f(*a, **k):
            order.append(name)
        return _f

    for name in TAIL_STEPS:
        monkeypatch.setattr(sleep_cycle, name, fake(name))
    asyncio.run(sleep_cycle._run_engine_independent_tail(
        bank, SimpleNamespace(), sleep_cycle._StageOutcome(committed=True)))
    return order


def test_a_demo_banks_sleep_takes_nothing_in_from_outside(tmp_path, monkeypatch):
    demo = tmp_path / "demo"
    bank_registry.scaffold_bank(demo, git_init=False)
    demo_guard.write_manifest(demo)
    assert _tail_order(monkeypatch, demo) == ["_refresh_state_safely", "_expire_claims_safely",
                                              "_warm_logos_safely", "_refresh_questions_safely"]


def test_a_real_banks_tail_is_unchanged(tmp_path, monkeypatch):
    real = tmp_path / "real"
    bank_registry.scaffold_bank(real, git_init=False)
    assert _tail_order(monkeypatch, real) == list(TAIL_STEPS)
```

Run it. Every gated route answers something other than 409 (a 422 for a required body, a 200 for the two polls,
a 404 for the unknown connector, and an `AssertionError` from `_no_local_reader` for the two bodiless syncs —
never a read of this machine's bookmarks or notes), the structural test fails on the missing dependency, and
the intake and tail tests fail. That is the red.

- [ ] **Step 2: The dependency.** In `api/routers/capture.py`, directly after `router = APIRouter()`, add

```python
def refuse_capture_into_demo(settings: Settings = Depends(get_settings)) -> None:
    """G141 capture-side track (R-CS15): a route dependency that answers ``409``
    with :data:`demo_guard.REFUSAL` while the ACTIVE bank is a demo bank.

    Route-level, so FastAPI solves it before the body is validated and before
    the handler runs (checked on 0.135.3): FastAPI has already read the body,
    but a folder batch or an upload is refused before any of it is staged.
    Every POST/PUT under ``/capture/`` and ``/sources/`` carries it unless
    ``test_demo_capture_routes.HANDLED_ELSEWHERE`` names why not — the Stop
    hook redirects, Telegram replies, the intake checks its target bank."""
    if demo_guard.is_demo(settings.memory_path):
        raise HTTPException(status_code=409, detail=demo_guard.REFUSAL)
```

- [ ] **Step 3: Gate the 16 routes.** In each of `api/routers/sources.py` and `api/routers/local_sources.py`,
  add `from api.routers.capture import refuse_capture_into_demo` after the `api.services` imports. After
  `router = APIRouter()`, add

```python
#: G141 capture-side track (R-CS15): every route below that takes something in
#: answers 409 while the demo bank is open, before its handler runs.
_DEMO_GATE = [Depends(refuse_capture_into_demo)]
```

Then add `dependencies=_DEMO_GATE` to each decorator. In `sources.py`, for example:
`@router.post("/sources/save", response_model=SourceSaveResponse, dependencies=_DEMO_GATE)`. The same for:
- in `sources.py`: `/sources/upload`, `/sources/rss`, `/sources/sync-bookmarks`,
  `/sources/sync-safari-tabs`, `POST /sources/feeds`, `/sources/poll-feeds`, `POST /sources/calendars`,
  `/sources/poll-calendars` and `/sources/sync-notes`;
- in `local_sources.py`: `POST /sources/folders`, `PUT /sources/folders/{folder_id}`,
  `POST /sources/folders/{folder_id}/sync`, `PUT /capture/local-source/wispr-flow/settings` and
  `POST /capture/local-source/wispr-flow`.

In `api/routers/connectors.py`, import it the same way and change only
`@router.post("/{connector_id}/sync", response_model=ConnectorSyncResult)` to add
`dependencies=[Depends(refuse_capture_into_demo)]`. Its `credentials` and `authorize` routes are NOT gated
(R-CS15).

- [ ] **Step 4: The intake's target.** In `api/routers/intake.py`, change `:44` to
  `from api.services import bank_registry, demo_guard, episode_staging, intake_jobs, media_ingestor`. In
  `resolve_target`, directly after `target = bank_registry.bank_dir(root, name)`, add

```python
    if demo_guard.is_demo(target):
        # G141 capture-side track (R-CS15): the TARGET bank decides, not the
        # active one — importing into your own memory while the demo is open
        # still works (`?bank=`), and nothing real is imported into the demo.
        # Checked before the scaffold, so a refusal creates nothing.
        raise HTTPException(409, demo_guard.REFUSAL)
```

- [ ] **Step 5: Sleep's tail.** In `_run_engine_independent_tail`'s guarded branch, replace

```python
        await _expire_claims_safely(memory_path)
        await _poll_connectors_safely(memory_path)
        await _poll_feeds_and_calendars_safely(memory_path)
        await _backfill_links_safely(memory_path, settings, user_triggered=user_triggered)
        await _resolve_papers_safely(memory_path)
        await _replay_wispr_todos_safely(memory_path)
```

with

```python
        await _expire_claims_safely(memory_path)
        from api.services import demo_guard

        if demo_guard.is_demo(memory_path):
            # G141 capture-side track (R-CS16): a demo bank's Sleep consolidates
            # its own made-up episodes but never takes in the outside world —
            # the connector credentials are machine-global, so a poll here would
            # pull the person's real saves into the demo.
            logger.info("demo bank: connector, feed/calendar, link-backfill, paper and Wispr to-do steps skipped")
        else:
            await _poll_connectors_safely(memory_path)
            await _poll_feeds_and_calendars_safely(memory_path)
            await _backfill_links_safely(memory_path, settings, user_triggered=user_triggered)
            await _resolve_papers_safely(memory_path)
            await _replay_wispr_todos_safely(memory_path)
```

Add one sentence to the function's docstring, after the G140 paragraph: "G141 capture-side track (R-CS16): on
a demo bank the outside-world steps are skipped; expiry, the state refresh, logos and the question refresh
still run."

- [ ] **Step 6: CLAUDE.md, the seventh Awake rail (R-CS18).** Change "Six rails hold across all of them:"
  (`:147`) to "Seven rails hold across all of them:". After the "A local source is read by the app and parsed
  by the backend" bullet (it ends "…one of the owner's listed / names." across `:190-191` at the base, which is
  `:193-194` once Task 2 has grown the rail sentence above it by three lines), add

```
- **Capture never writes into a demo bank** (G117's synthetic bank; G141 capture-side track). A bank
  is the demo when `<bank>/_bank.yaml` says `kind: demo` — written first by `demo_bank.populate` and
  committed as `cicada` — or, for a demo made before that file, when its `.git/config` carries the
  generator's identity; never by its name (`api/services/demo_guard.py`). While it is active: every
  POST/PUT under `/capture/` and `/sources/` answers **409** (one route dependency,
  `refuse_capture_into_demo`, and a test that fails for a new route that is neither gated nor named);
  the intake checks the bank it writes into, so `?bank=` into your own memory still works; the MCP
  write tools refuse with a sentence the agent relays; Telegram answers 200 with a reply saying
  nothing was saved; and the Stop hook saves the session into the real bank left most recently
  (`last_active_at`, stamped by `activate_bank`; the response says `bank` and `redirectedFrom`), or
  answers 409 when it cannot tell which — the next reply after switching back saves the whole
  session. A demo bank's Sleep consolidates its own made-up episodes, but its tail skips the
  connector, feed/calendar, link-backfill, paper and Wispr to-do steps (connector credentials are
  machine-global). The generator itself is never gated.
```

- [ ] **Step 7: Green.**

```
cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_demo_capture_routes.py api/tests/test_demo_capture.py api/tests/test_intake.py api/tests/test_intake_jobs.py api/tests/test_banks.py api/tests/test_source_channels.py api/tests/test_telegram_capture.py api/tests/test_sleep_connector_poll.py api/tests/test_sleep_feed_poll.py api/tests/test_sleep_link_backfill.py api/tests/test_claim_expiry.py -q -p no:cacheprovider
cd <worktree> && api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider
```

→ 0 failures. If a pre-existing test posts to a gated route on a bank whose `.git/config` names
`demo@cicada.example` (the grep at plan time found none: `demo_bank.populate` runs only in
`test_demo_bank.py` and `test_entity_provenance.py`, and neither posts to a gated route), that test is
exercising a demo bank and gets the 409 by design. Stop and report it; do not weaken the gate.

- [ ] **Step 8: Commit.** Stage `api/routers/capture.py`, `api/routers/sources.py`,
  `api/routers/local_sources.py`, `api/routers/connectors.py`, `api/routers/intake.py`,
  `api/services/sleep_cycle.py`, `api/tests/test_demo_capture_routes.py` and `CLAUDE.md`. Message:
  `fix(G117): every capture route, the intake and Sleep's tail refuse the demo bank`. The body cites
  R-CS15, R-CS16 and R-CS18 and flags the new seventh CLAUDE.md rail, then gives the attribution lines.

---

### Task 5: Docs: merge `dev`, then G141 PJ-0/PJ-4 done, PJ-0b next, the G117 capture guard

**Files:**
- Merge: local `dev` into this branch (Step 0). Since the base it changed docs and `app/` only, and it carries
  the owner's 2026-09-23 rulings on the G141 DECIDEs, which rewrote the very TODO.md paragraph and G141 row this
  task edits. Editing the base's text would conflict at PR time and would restate a DECIDE as open after the
  owner ruled it.
- Modify (line numbers are `dev` @ `364e6b4`; re-read after the merge, `dev` may have moved):
  - `docs/goals/TODO.md`: the "Pick up here" G141 paragraph (`:270-276`), queue item 13b (`:579-590`) and the
    ruled G141 DECIDEs (`:663-670`);
  - `docs/goals/memory-evolution.md`: the G141 row (`:705`) and the G117 row's status cell (`:681`).

Privacy: no names from any bank, no conversation text, no episode titles. The PR number is written `PR #88`,
and the orchestrator fills it in at merge.

The `TODO.md` phrases below wrap across lines in the file:
- "Screenshots come from a freshly generated demo bank only." spans `:275-276`;
- the 13b slice list spans `:584-585`, and "Open DECIDEs (rail cell, band colour, pending-store hold) are under
  Research / decisions below" spans `:589-590`;
- the ruled DECIDE (c) sentence ("(c) **yes** — Sleep holds … a new slice **PJ-0b** after PJ-0.") spans
  `:668-669`.

Match the words, not the line breaks, and keep the file's ~110-column wrap in what you write. The two
`memory-evolution.md` rows are single table lines: edit them in place and never add a newline inside a row.

- [ ] **Step 0: Merge `dev`.** First confirm it brings no code:
  `cd <worktree> && git diff --stat 8fde352 dev -- api mcp` must print nothing. If it prints anything, stop and
  report: a code anchor under Tasks 1–4 may have moved. Then run
  `cd <worktree> && git merge --no-ff dev -m "Merge branch 'dev' into feat/g141-capture-side" -m "Brings the owner's 2026-09-23 G141 rulings (docs only) under the doc edits that follow." -m "<the attribution lines>"`.
  No conflict is expected: `dev`'s CLAUDE.md hunks start at the base's `:553`, outside the regions Tasks 2 and 4
  edited (`:147-191`, `:346-348`, `:841-842`; `dev`'s `:757` hunk ends at `:763`), and this branch has not
  touched `docs/goals/` yet. On any conflict, `git merge --abort` and report. Then re-run the four new test
  files and `api/tests/test_capture_transcript.py` (green), and confirm
  `cd <worktree> && git diff --stat dev -- app/` is still empty.

- [ ] **Step 1: `TODO.md`.** In "Pick up here", directly after the G141 paragraph (it ends "Screenshots come from
  a freshly generated demo bank only.") and before `dev`'s "**Filed 2026-09-23 — G61 phase 2…**" paragraph, add
  this paragraph:

```
**PJ-0 and PJ-4 shipped (PR #88, `feat/g141-capture-side`)**, with a fix found the same day: capture can no
longer write into a demo bank (`api/services/demo_guard.py` — the Stop hook saves into the real bank left most
recently, every other writer refuses; CLAUDE.md's seventh Awake rail). Next on the backend: **PJ-0b** (hold a
page-less subject's claims with its pending entity, ruled 2026-09-23; the seam is
`claim_pipeline.hold_page_less`) and **PJ-1**.
```

In 13b, replace "**PJ-0** page-less claim fix · **PJ-1** read model + `GET /projects[/{id}/timeline]` ·
**PJ-4** Stop-hook turn stamps — all three backend, $0, **start now**;" with "**PJ-0** page-less claim fix ✅ ·
**PJ-4** Stop-hook turn stamps ✅ (both PR #88) · **PJ-0b** hold page-less claims with the pending entity (ruled
2026-09-23) · **PJ-1** read model + `GET /projects[/{id}/timeline]` — backend, $0, **start now**;". In the same
item, replace "Open DECIDEs (rail cell, band colour, pending-store hold) are under Research / decisions below"
with "The three DECIDEs (rail cell, band colour, pending-store hold) were ruled 2026-09-23 — see Research /
decisions below".

In the ruled G141 DECIDEs, change "a new slice **PJ-0b** after PJ-0." to "a new slice **PJ-0b** after PJ-0 — its
seam, `claim_pipeline.hold_page_less`, shipped with PJ-0 (PR #88) and holds nothing until PJ-0b." Leave the
rest of the paragraph, the owner's quote included, as it is.

- [ ] **Step 2: The G141 row.** Directly before "**Carry-forward:**", insert

```
**Shipped 2026-09-23 (PR #88, `feat/g141-capture-side`).** PJ-0: Stage 2 returns its `name_to_id` and Stage 5.56 keys every claim endpoint through it (`entity_resolver.endpoint_id`, the edge rule as one function), maps the closed owner surfaces ("the user", "me", …) onto the `owner: true` page, and counts the claims whose subject still has no page (`claims_page_less`: counts in the log, the claim ids at DEBUG, never a subject; carried into the `sleep_run` row as M3's measure); the false "re-emitted next cycle" comment is gone, and the R-PJ17 hold is `claim_pipeline.hold_page_less`, a seam that holds nothing until PJ-0b (the hold was ruled yes on 2026-09-23). Claims now follow Stage 2's matches, its fuzzy merges included (disclosed; G98's). PJ-4: the Stop hook writes `turns: [{offset, ts, speaker}]` through `episode_staging.stamps_for` (the hook's `role: text` body is the stager's line shape byte for byte, so the spec's "cannot reuse" did not hold), outside the hash, the last key, head-stable at 500; the episode `timestamp` stays the session's start, a pre-PJ-4 episode keeps its count until its session's next rewrite, and a lint keeps the `turns` key to its three modules.
```

Then replace ONLY the carry-forward's first sentence, "**Carry-forward:** the on-disk `memory/banks/demo` holds
one non-synthetic capture, so every screenshot and fixture comes from a freshly generated demo bank.", with the
two sentences below. Keep the "**Ruled 2026-09-23 (owner: …)**" sentence that follows it on `dev` exactly as it is.

```
**Carry-forward:** the on-disk `memory/banks/demo` holds one non-synthetic capture, so every screenshot and fixture comes from a freshly generated demo bank. From this track on no capture writer can write into a demo bank (`demo_guard`, see G117), so the leak cannot recur; the old copy still needs regenerating.
```

- [ ] **Step 3: The G117 row.** At the end of its status cell (the fourth cell, which ends "…the evening
  reminder."), just before the closing ` |`, append

```
 **Capture guard (2026-09-23, G141 capture-side track, PR #88):** while the demo bank was open for screenshots, a real Claude Code session's Stop hook wrote into it (quarantined by hand). A demo bank is now marked in the bank (`_bank.yaml`, `kind: demo`; an older one by the generator's git identity), every capture writer refuses it in plain words, the Stop hook saves the session into the real bank left most recently (or answers 409 when it cannot tell which), and a demo bank's Sleep tail skips its outside-world steps.
```

- [ ] **Step 4: A privacy read.** Run
  `cd <worktree> && git diff dev -- docs/goals CLAUDE.md | grep -n -i "http\|@\|/Users/"` (against `dev`, so the
  CLAUDE.md edits committed in Tasks 2 and 4 are included). Expect no hit; the only acceptable one is the
  generator's placeholder `demo@cicada.example`, if a line names it. Then read that diff once for names.
- [ ] **Step 5: Commit.** Stage `docs/goals/TODO.md` and `docs/goals/memory-evolution.md`. Message:
  `docs(G141, G117): PJ-0 and PJ-4 shipped, PJ-0b next; capture never writes into a demo bank`, then the
  attribution lines.

---

## Not in scope

These are named so a reviewer does not read an absence as an oversight.

- **Holding page-less claims in the pending store** (R-PJ17). The owner ruled it yes on 2026-09-23 (on `dev`,
  `ef4c8d8`), as its own slice **PJ-0b** after PJ-0: it changes the pending store. Only the seam ships here
  (R-CS4).
- **Owner surfaces in Stage 2's edges, or stopping Stage 2 from promoting a junk `user` page.** PJ-0 maps
  claims only. A claim-derived edge reaches the owner page through Stage 5.7 anyway.
- **Tightening Stage 2's `fuzz.ratio > 85` matcher.** That is G98's (R-CS5).
- **Backfilling `turns` on older Stop-hook episodes, or a tail-keeping cap.** Neither is done (R-CS8). A
  tail-keeping cap is a RESEARCH row only if M5 shows many sessions past 500.
- **`when.py`, `date_basis` and dating happenings.** These are PJ-3's. PJ-4 only stores the times (R-CS9).
- **Removing a leaked capture already in a demo bank** (R-CS19), and regenerating the owner's on-disk demo
  bank. Both are manual, owner-side.
- **Anything in the app:**
  - a "demo is open" banner;
  - a `demo` flag on `/banks` rows;
  - how the folder / browser / Wispr watchers behave after a 409 (unchanged: their existing failure
    handling).
- **Redirecting MCP, Telegram or any writer other than the Stop hook** to a real bank. The brief rules that
  they refuse.
- **Gating `cicada_resolve_inbox` and `cicada_mark_processed`** (R-CS13), and any read.
- **Writes into the active bank that are not capture.** Disclosed so a reviewer can rule on them:
  - `PUT /settings/owner` writes the owner's `person` page into the ACTIVE bank
    (`owner_identity.ensure_owner_entity`, `routers/settings.py:30-58`). With the demo open, the person's own
    name lands in the demo bank. It is a settings write, not capture, and the demo already carries its own
    owner page, so this track leaves it; a follow-up can refuse it the same way or write the name to
    `owner.json` only.
  - `POST /entities/{id}/sources` and `POST /inbox/{id}/resolve` are the person curating what is on screen,
    the demo included.
  - Stage 5.57's link enrichment inside the cycle and the user-triggered `POST /maintenance/enrich-links` fetch
    pages for links the bank already holds. On a demo bank those are its own made-up `example.com` links, so
    nothing of the person's comes in; only the tail's link *backfill* is skipped, with the other outside-world
    tail steps (R-CS16).
- **A choke-point guard in `episode_ids` / `episode_staging`** (R-CS17).
- **Any wire change beyond** `POST /capture/transcript`'s two additive keys and the remote `demo` status. No
  ETag, no `VersionVector` mapping, no `/banks` field moves.
- **DESIGN_RULES.** Nothing here is UI.

---

## Verification the orchestrator runs at the end

1. **The full suite.** Run `cd <worktree> && api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider`.
   Expect **0 failures**, ≥ 3167 passed plus the new tests (65 as written here:
   - 12 in `test_claim_pipeline_subjects.py`;
   - 8 in `test_transcript_turn_stamps.py`;
   - 22 in `test_demo_capture.py` (the write-tool test is 5 parametrized cases);
   - 23 in `test_demo_capture_routes.py` (the gated-route test is 16 parametrized cases).

   Re-count from the collected output, never trust this estimate.) If
   `test_agent_provenance.py::test_a_decay_only_change_lands_in_its_own_cicada_authored_commit` is the only
   red, re-run it alone and report both results.
2. **No app change.** `cd <worktree> && git diff --stat dev -- app/` → empty. The Swift suite is not
   affected and need not run.
3. **The integer is gone.** Run
   `cd <worktree> && grep -rn "[\"']turns[\"']" api mcp | grep "\.py:" | grep -v "/tests/"`. It should show
   only `episode_staging.py`, `evidence.py` and `transcript_capture.py` (`_place_turns`). None of the lines is
   `len(conv.turns)`.
4. **The false comment is gone.**
   `cd <worktree> && grep -rn "re-emitted next cycle\|waits for its subject to be promoted" api` → no hit.
5. **A lint that has never failed is not known to work.** Temporarily delete `dependencies=_DEMO_GATE` from
   the `/sources/poll-feeds` decorator in `sources.py` (a route with no body and no local read) and run
   `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_demo_capture_routes.py -q -p no:cacheprovider`.
   It must go red (the structural test plus that route's 409 case). Revert, and confirm it is green again.
   `_no_local_reader` keeps this safe for any other route too: a bodiless sync that reaches its handler fails
   loudly instead of reading this machine's bookmarks or notes.
6. **Diff read for the rails.** Check that:
   - no `logger.` line in the diff interpolates a subject id, a claim's text or episode text;
   - the new `sleep_run` refs are integers;
   - `demo_guard.py` imports only `re`, `pathlib` and `yaml`;
   - `api/hooks/capture.py` still imports nothing from `api`;
   - nothing keys on the bank name "demo".
7. **Owner-present check after merge** (the orchestrator or the owner; never a build agent, because it reads
   `~/.cicada`):
   - generate a fresh demo bank;
   - make it active;
   - let one Claude Code reply finish;
   - confirm that `~/.cicada/logs/capture.log` shows `http 200 created into <bank> (the demo memory is open)`,
     and that the demo bank's `episodes/` did not change.
8. **The PR body must state:**
   - **the owner-visible CLAUDE.md changes:** the Stop hook's `turns:` rail sentence is amended (R-PJ16: it is
     no longer an integer count), and a seventh Awake rail is added ("Capture never writes into a demo bank");
   - the only wire additions: `bank` + `redirectedFrom` on `POST /capture/transcript`, and the remote
     `remote_call` status `demo`. No ETag or `VersionVector` mapping changed;
   - PJ-0's disclosed behaviour: claims now follow Stage 2's matches, fuzzy merges included (R-CS5);
   - **R-PJ17's hold was ruled yes (2026-09-23) and is slice PJ-0b**: this PR ships only its seam,
     `claim_pipeline.hold_page_less`, which holds nothing yet;
   - the disclosed non-capture writes that still reach an open demo bank, `PUT /settings/owner` first (see
     Not in scope), for the owner to rule on;
   - that `api/services/demo_bank.py` is also where PJ-1 adds its `today=` seam to `populate`: whichever of the
     two PRs lands second keeps both the manifest-first line and the new parameter.
