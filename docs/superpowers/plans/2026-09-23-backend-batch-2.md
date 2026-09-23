# Backend fixes, batch 2 (Track F2-back) — Implementation Plan

> **For agentic workers:** execute task by task, in order, in this one worktree. Steps use checkbox
> (`- [ ]`) syntax. No subagents. Every task is one reviewable commit that leaves the branch
> shippable: failing test → implement → green → the task's suites → commit.

**Goal:** Seven backend defects found in the owner's live review and the round-3 merges, fixed with
no app change. **(1)** Two Cicada writers committing to one bank at once collide on git's
`index.lock`, and the loser's pages stay dirty for the next `git add -A` writer to sweep under its own
author (the G85-class smear). After this track there is one git writer per bank, git's own lock is
waited out, and a commit that still fails is kept, said on its channel, and landed later under its
own author. **(2)** Changing a watched folder's authorship rules leaves its existing episodes with
the old `evidence_kind` unless the app re-posts every byte. After this track the backend re-derives
them in place when the rules are saved. **(3)** `GET /remote/status` says ngrok is not installed
under launchd's bare PATH. **(4)** The `mcp-agentic-write` placeholder shows as a contributor.
**(5)** Paper why-claims carry `[N50](#note-n50)` anchors. **(6)** The video and meeting skill
bridges are still off although their Cicada tools shipped. **(7)** `/state`'s `sleep.next_at` —
already calibrated on `dev`, so this track pins it and corrects the stale disclosure.

**Architecture:** One lock object per resolved bank path in `git_service`, held by a worker thread
for a whole add → status → commit sequence, is the only way a mutating git command runs; the async
commit helpers become `asyncio.to_thread` wrappers over sync ones, the seven direct-subprocess
writers call the sync ones, and a lint keeps any new writer from spawning git itself.
`folder_source.commit_paths_for` gains a write-ahead ledger in the bank's git dir. Authorship
re-derivation reuses the stager's own queue rule through one new frontmatter-only function. Agent
labels reuse the `harness` kind the app already renders, and the three reads that serialise an author
kind fold one shape tag into their ETags. Paper text cleaning is one pure function plus a one-shot
repair in F1's exact shape. No LLM anywhere; no new endpoint, ETag component or Store domain.

**Tech Stack:** Python 3 / FastAPI / pytest (`api/`), markdown + git bank. No Swift.

**Spec:** `docs/superpowers/specs/2026-09-23-round3-meadow-reach-provenance-design.md` — Decisions 4
(Cicada never opens a tunnel), 8 (skills are proposals; excerpts, never transcripts) and 9 (papers),
and Track R/F/N rulings R-R5, R-F2, R-N2 bind. Other binding context:
`docs/superpowers/plans/2026-09-23-local-sources.md` (R-LS10 agent files never queued, R-LS17 paper
writes wait while Sleep runs, R-LS30 folder commit authorship),
`docs/superpowers/plans/2026-09-23-owner-feedback-1.md` (R-FX5 paper ids name the slot; R-FX6 the
repair shape), `docs/superpowers/plans/2026-09-23-settings-v3.md` (R-O27 install state, R-O28 pending
bridges). Backlog rows: **G85** (the smear), **G135** (harness labels, R-R26), **G118** (spans, not
copies), **G133** (folders, papers), **G134** (speakers), **G138** (bridges), **G140** (the watch
record), **G125** (schedule modes). Standing rulings: TODO ruling 3 (no derived artifact tracked),
the privacy rule, ETag ship-together, Sleep safety, portability.

---

## What the code actually does today (verified against `fix/backend-batch-2` @ `edfd6de`)

**Git writers.**
- `api/services/git_service.py:403-421` — `_run_git` spawns `git` with `asyncio.create_subprocess_exec`
  for reads and writes alike; no lock, no retry. `:1153-1162` `commit_changes` (`add -A` → `status`
  → `commit` → `rev-parse`) and `:1165-1178` `commit_paths` (`add --` → `status --` → `commit --`)
  are four and three separate `_run_git` awaits, so two writers interleave freely. `:1189-1233`
  `commit_resolution` calls `commit_changes`.
- **Reproduced on a synthetic bank (scratch script, 2026-09-23):** eight `asyncio.gather`ed
  `commit_paths` calls on one bank failed in **5 of 5 trials**, each time with
  `git add -- entities/page-N.md failed: fatal: Unable to create '…/.git/index.lock': File exists`,
  leaving **6–7 of the 8 pages dirty**. Git 2.50's refusal text is exactly
  `Unable to create '<path>/.git/index.lock': File exists.` (checked in a scratch repo).
- **Direct subprocess writers outside `git_service`** (each `subprocess.run(["git", "add"|"commit", …])`):
  `inbox_migration.py:189-219` (`_commit_migration`) and `:297-318` (`_commit_dedup`);
  `placeholder_summary_migration.py:105-116`; `paper_context_migration.py:119-130`;
  `decay_migration.py:126-164`; `export_origin_migration.py:91-103`;
  `decay_watermark_migration.py:306-335`; `claim_expiry.py:146-157` (`restore`: `git checkout -- …`).
  `inbox_service.py:324-350` runs `git mv` / `git rm` through `_run_git`. Not writers:
  `bank_registry.py:338` (`git init`, before any writer exists), `demo_bank.py:367-374` (`git config`),
  `repo_context.py:73-80` (reads the person's code repos, never a bank), `state_dictionary.py:371-379`
  (`git log` only).
- **Callers that bridge threads into the async helpers:** `agent_commits.py:57`,
  `calendar_registry.py:455` and `demo_bank.py:352` call `asyncio.run(git_service.commit_*(…))` from
  a thread with no loop. Migrations run synchronously on the loop thread at startup
  (`main.py:141`, before the scheduler starts at `:155-159`) and in the threadpool on a bank switch
  (`routers/banks.py:115`, `:262`).
- **Readers that can hold the index lock:** `git status` takes `index.lock` opportunistically to
  refresh its stat cache. In-process callers: `git_service.porcelain_status` (`:1181-1186`) and
  `sleep_cycle._dirty_paths` (`:755`).
- **The incident's path:** `paper_metadata.run_locked:458-482` commits in its `finally` through
  `folder_source.commit_paths_for:494-510`, which catches every exception and only logs a warning
  (`:509-510`). Nothing records the failure and nothing retries the paths; the next `git add -A`
  writer (Sleep's `_finalize` at `sleep_cycle.py:1990`, a feed poll, Telegram) sweeps them. Other
  `commit_paths_for` callers: `routers/local_sources.py:63, :75, :85, :158, :177, :206`,
  `sleep_cycle.py:496` (folder papers) and `:525` (Wispr to-dos).
- **Precedent for a kept-paths journal:** `decay_watermark_migration.py:58-68, :129-172` — a
  `.decay_watermarked.pending` write-ahead list, unioned on retry and cleared after a successful
  commit.

**Authorship rules.**
- `routers/local_sources.py:67-77` — `PUT /sources/folders/{id}` calls `folder_source.update:170-182`
  (saves `folders.json`) and commits only `sources/folders.json`. No episode is touched.
- `folder_source.py:301-318` — `drafts_for_file` puts `authorship` and
  `evidence_kind: user|assistant` in the episode frontmatter and sets `queue_for_sleep` from the
  rule. `:407-411` — `sync` treats a posted file as unchanged only when both `content_sha` and
  `evidence_kind` match the CURRENT rules, so a re-post of the same bytes re-derives
  (R-LS10's "change a glob and sync again").
- `episode_staging.py:308-322` `_refresh` and `:325-353` `_requeue_for_authorship` are the
  metadata-only path: parser-only → queued when now the owner's; unconsolidated → parked
  (`processed: true, processed_by: parser`) when now an agent's; **an episode Sleep consolidated is
  never un-processed**. `_refresh` also clears `source_deleted_at` (a returning file).
- **The app** (`LocalSourceWatcher.swift:427-434`, `updateAgentGlobs`) drops its manifest after the
  PUT and re-posts every file. The owner's review found episodes still stale after a rules change,
  and the orchestrator re-posted files by hand. The backend is the one place that can make this hold
  whatever the app sends.
- **Where the span kind is read (verified for R-B8).** A claim's `evidence[].kind` is minted at write
  (`evidence.verify:525-548`) and stored. `/episodes/{id}/text` re-derives every turn's role and an
  asserted focus's kind from the episode's CURRENT `evidence_kind` through `evidence.kind_for`
  (`provenance.py:71-79, :127-129`). `transclusion_resolver.claim_to_model:74` (claim chips) and
  `provenance.py:452` (`/episodes/{id}/citations`) ship the STORED kind. Stage 1 reads the episode's
  override at extraction (`entity_extractor.py:380`). Paper claims read `authorship` from the episode
  frontmatter at every re-parse (`papers.py:651`).

**Remote status.** `api/remote/reach.py:64-66` — `detect` finds ngrok only through `shutil.which`
and Tailscale through `which` or the app bundle. Its docstring (`:4-5`) says the plist's PATH has
`/opt/homebrew/bin` and `/usr/local/bin`. That is true of a plist `install.sh:355` writes today, and
false of an older one: `install.sh` never rewrites a plist behind a running backend (CLAUDE.md,
"Reaching the outside world"). The same PATH trap for the engine CLIs was fixed with a fallback list
(`connections/base.py:72-83`, the 2026-09-02 incident).

**Agent labels.**
- `agentic_write.py:93-103` — `_ReconcileSettings.litellm_model = "mcp-agentic-write"`. Through
  `claim_reconciler._stamp_new:120-129` → `engine_select.author_model:98-113`, every claim that
  reaches `write_claim` without `authored_by` is stamped with it. Callers that pass none today:
  `telegram_capture.py:328-345` (the person's own `saved-because` reason), `wispr_flow.py:434-437`
  (a note-taker's to-dos, `assistant` spans), `demo_bank.py:321`. MCP writes pass the harness label
  since G135 R-R11 (`mcp_tools.py:895-916`, `agent_commits.author_for:29-34`).
  `papers.py:374` stamps `authored_by=None` on an agent-authored folder file's claims, which reads as
  `unknown` ("Before provenance" in the app).
- `agentic_write.py:553` `_LEGACY_MCP_AUTHOR` is the shim's value; `owns:557-577` lets any local agent
  withdraw a placeholder claim only on an `mcp` origin.
- `git_service.py:311-362` — `_classify_author_kind` answers `user | system | unknown | model`, so a
  harness label (`claude-code`, `claude-web`, `agent`) and the placeholder are "models" (`claude-code`
  even gets provider `anthropic` from the `claude` substring). Readers: `author_identity` (claims
  `transclusion_resolver.py:53`, history `git_service.py:502`, provenance `provenance.py:283`) and
  `get_contributors:829-839`.
- **The app already renders a `harness` kind** that the backend never sends:
  `ContributorIdentity.swift:40` names it with `OriginIconography.label(for: author)` and
  `ContributorsView.swift:317` draws `OriginMark(origin: author)`. The G118 row lists "a remote write's
  app label bucketed as `harness` by `author_identity`", and the G135 row lists "a dedicated `harness`
  contributor kind (R-R26)", both as open. `source_overview.HARNESS_LABELS:132-147` is the one table
  of every harness label (stdio harnesses and every remote app's).

**Paper claim text.** `papers.py:80-82` `BULLET_RE` captures everything after the dash as `note`.
`:383-386` passes the note as the `saved-because` object, text and evidence quote, and `:366` mints
the id from `(entity, predicate, object, observer, slot)`. A note written as
`builds on [N50](#note-n50).` therefore stores the anchor in the claim. `apply_claims:431-446` never
rewrites an existing claim's text. F1's repair shape is `paper_context_migration.py` (marker,
`folder_source._LOCK`, per-page robustness, commit what landed, marker off on failure) wired in
`bank_migrations.py:98-106`.

**Skill bridges.** `api/data/recommended_skills.json:36` (`watch` → `video`), `:70`, `:84`, `:158`
(`wispr-flow`, `granola`, `transcribe` → `meetings`) and `:128` (`pdf` → `documents`) are
`"active": false`. `skill_catalog.py:20-23` says they wait for the watch record (shipped, G140) and
speaker-aware evidence (shipped, G134). `BRIDGE_TEXT:49-52` has only `papers`. `bridge_lines:185-209`
emits a line only for an active bridge whose entry is INSTALLED in that agent; `mcp-hosted` entries
are always `unknown` (`installed_state:101-120`, R-O27). Pins: `test_skill_catalog.py:62` (watch
inactive), `:65-78` (a naive R12 split — arguments must be plain names), `:164-175` (uses `watch`
as the installed-but-inactive example); `test_handshake_r12.py:62-72` holds every bridge line to
R12 on every local variant. `evidence._SPEAKER_RE:88` reads `speaker:<label>:` in ANY episode, and
`mcp_tools.save_episode:1758-1818` stores content verbatim after the scrub. `cicada_record_watch`
saves an unsaved link first (`mcp/server.py:310`).

**`sleep.next_at`.** Already fixed on `dev` by `7d1de42` (Track P R6): `routers/state.py:106-124`
calls `sleep_scheduler.next_run_at` with `last_cycle_at` and `newest_unprocessed_at` from the same
`sleep_debt.compute` that `routers/status.py:103-110` uses. It is pinned for daily, interval and
after_import at `test_state_wiring.py:202-263`. `manual`, the empty after_import queue and parity
with `/status` are unpinned. `docs/goals/TODO.md:331-339` still carries the "Disclosed gap" as open.

**Baselines:** `dev` is all green, 3167 passed (the orchestrator, 2026-09-23). The twelve files this
plan edits most were re-run here: 306 passed. **Re-measure before Task 1.**

---

## Global Constraints

- Work ONLY in `<worktree>` = `<repo>/.worktrees/f2b`, as the absolute path the orchestrator gave
  (branch `fix/backend-batch-2`). Every shell command is `cd <worktree> && <cmd>` with the ABSOLUTE
  path (zoxide hijacks relative `cd`; ignore its stderr warning). No `grep --include=*.ext` (zsh
  globs it); use `rg` or quote it.
- NEVER read `<repo>/memory` (any bank), `~/.cicada`, `~/Library/Safari` or `~/.claude/projects`.
  Fixtures are synthetic: `alpha-project`, `bob-example`, `example.com`, arXiv `2401.00001`,
  DOI `10.1234/example.5678`, folder label `alpha-project`, path `/Users/example/alpha-project`.
- Python: `cd <worktree> && api/.venv/bin/python -m pytest <files> -q -p no:cacheprovider`. The full
  `api/tests` must be **0 failures**. If
  `test_agent_provenance.py::test_a_decay_only_change_lands_in_its_own_cicada_authored_commit` is the
  ONLY red, re-run it alone and report both results.
- **Backend only:** `api/`, `mcp/`, `api/data/`, `scripts/`, `docs/`. No file under `app/` changes —
  another track is redesigning the app. App behaviour this track relies on is cited, not edited.
- Never `git add -A`; stage named files only. Never commit `memory/`, `logs/`,
  `.claude/settings.json`, `api/.venv` or `*-report.md`. No push, no branches or worktrees, no
  subagents. Ignore Devin/PR comments.
- **Sleep safety:** no LLM anywhere in this track; the migration and every read path stay
  engine-free; paper writes still wait while a cycle runs (R-LS17).
- **ETag ship-together:** no component is added and no client mapping changes. Episode rewrites move
  the existing `episodes` component; `folders.json` is already in `sources` (R-LS29). The one recipe
  touch is Task 4's shape tag (R-B10): `/contributors`, `/entities/{id}/provenance` and
  `/episodes/{id}/citations` fold `git_service.AUTHOR_SHAPE` into their `extra`, because R-B9/R-B10
  change those bodies for the same inputs — the `graph.NODE_SHAPE` precedent. Without it the app's
  on-disk `/contributors` snapshot would 304 the old kinds until the next commit.
- **Git rails:** a new writer never spawns a mutating git command itself (Task 1's lint). Never delete
  an `index.lock`.
- **Privacy:** no owner name, no real page, folder or section name, no count read from the live bank
  in code, tests, docs, commits or PR bodies. Write `<worktree>` / `<repo>` in docs.
- Docstrings explain **why** and cite the ruling or G-row (`R-B…`, G85, G135, G118, G133, G138), at
  the density of the files touched. Line numbers above are from `edfd6de`; read before editing.

---

## Rulings (binding)

Where the brief left a choice, it is decided here with its reason, so no task re-opens it.

- **R-B1 — One git write lock per bank, in this process.** `git_service.write_lock(memory_path)` is a
  `threading.RLock` keyed by `os.path.realpath` of the bank. It is taken by every mutating git
  command: `commit_paths`, `commit_changes`, `commit_resolution` (through `commit_changes`), a
  `_run_git` whose subcommand is in `WRITE_SUBCOMMANDS`, the seven migrations' commits and the
  expiry restore. **The backend is one process:** `install.sh`'s plist runs one uvicorn worker, and
  the G135 remote listener is a second server inside that process. So a process-local lock
  serialises every Cicada writer that can collide in-process. Cross-process safety — the stdio MCP
  server's `agent_commits`, the person's terminal, an Obsidian git plugin — is git's own `index.lock`
  plus R-B2's retry, and is not widened here. *Revisit:* if the backend ever runs more than one
  worker, this lock stops being the whole answer.
- **R-B2 — Retry only git's index-lock refusal; never delete the lock.** Stderr containing both
  `index.lock` and `File exists` is retried: five tries, waiting `(0.1, 0.25, 0.5, 1.0)` s between
  them (about 1.85 s). Anything else fails at once. The wait happens with the bank lock held, so
  in-process writers queue behind it instead of stampeding. Another process owns that lock, and
  removing it under a live commit corrupts the index. A lock that outlasts the retries (an editor
  left open by `git commit`) becomes R-B5's problem.
- **R-B3 — Reads never take the index lock.** `_run_git` runs every non-write with
  `GIT_OPTIONAL_LOCKS=0`. `git status`'s opportunistic stat-cache refresh is otherwise exactly the
  "other process" a Cicada writer trips over. Reads never wait on the write lock.
- **R-B4 — The whole sequence runs in one worker thread.** `commit_paths_sync` / `commit_changes_sync` /
  `run_git_write_sync` take the lock and spawn with `subprocess.run`. The async `commit_paths` /
  `commit_changes` are `asyncio.to_thread` wrappers with unchanged signatures. Why a thread lock and
  not an `asyncio.Lock`: the writers span asyncio tasks, the threadpool, `asyncio.run` bridges on
  threads with their own loops (`agent_commits`, `calendar_registry`, `demo_bank`) and sync startup
  migrations. An `asyncio.Lock` cannot be shared across loops, and a thread lock taken on the loop
  thread by an `await`ing holder would stall the loop. Holding it for add → status → commit means a
  `status` check and its commit never straddle another writer. A thread always runs to completion, so
  a cancelled Sleep cycle can no longer abandon git halfway.
- **R-B5 — A commit that still fails is kept, said, and landed later under its own author.** Scope:
  `folder_source.commit_paths_for` — every folder, paper and Wispr commit, the incident's path. Other
  writers get R-B1/R-B2 only (Not in scope). It gains `channel` and returns `bool`. Before committing
  it writes the paths to a ledger (the `.decay_watermarked.pending` write-ahead shape), keyed by
  `trigger|author|channel`. On success it drops the paths it committed (the entry goes with its last
  path), and clears the channel's error when that error is ours. On failure it keeps them and records `COMMIT_FAILED_MESSAGE` with
  `sync_state.record_error(channel)`. The ledger is edited **by path, never by whole entry**: the
  write-ahead and a refusal add this call's paths, a success drops exactly the paths it committed
  (plus kept paths whose file is gone). Two overlapping runs of one writer (the watcher's batch and
  a manual Sync of the same folder) therefore never erase each other's kept paths. The ledger is
  `<own git dir>/cicada-pending-commits.json` (`bank_registry.git_dir`), never in the tree. G136 R2's
  reason applies: a tracked file dirtied here would be swept into the next `git add -A` commit. The
  own git dir is `<bank>/.git`, or a worktree's or submodule's `gitdir:` target, **never** the common
  dir `_git_dir` follows for `info/exclude`. Two worktree banks share one common dir, and one
  bank's kept paths must never be committed by the other's writer. A bank with no `.git` of its own is never
  committed (git would climb into an enclosing repo, the `agent_commits` refusal). The same writer's
  next call carries the kept paths. **`sleep_cycle.run` flushes every kept entry before any stage
  writes**, because `_finalize`'s `git add -A` is the most frequent sweeper. `paper_metadata.run_locked`
  stamps `record_sync` only when the commit landed, so a success line never hides the failure.
- **R-B6 — Saving authorship rules re-derives the folder's existing episodes in place.** `PUT` with
  `authorship` (and a re-pick `POST` that carries rules) calls
  `folder_source.reapply_authorship(memory_path, folder_id)`. It is idempotent and runs on every save
  that carries rules, not only on a detected change. That also repairs a folder whose rules changed
  before this fix. For each episode of the folder it computes `authorship_for(relpath, rules)` and,
  when `authorship`/`evidence_kind` differ, rewrites **frontmatter only** through the new
  `episode_staging.reattribute`. Body, `content_hash`, `content_sha`, `source_id` and the `turns`
  sidecar are untouched, so every evidence span stays `current`. The re-derivation and `folders.json`
  land in **one** `commit_paths_for` commit: `Cicada-Author: user`, trigger `folder/authorship`,
  subject `Folder settings (<label>)`, channel `folder:<id>`. *Declined:* a 409 while Sleep runs.
  The app re-posts every file right after the PUT and `sync` re-derives through `_refresh` during a
  cycle already, so refusing the PUT would add a failure mode the app has not built for and close no
  race (disclosed in Not in scope).
- **R-B7 — What `processed` becomes is the stager's existing rule, unchanged.**
  `_requeue_for_authorship`: an agent → owner episode that only the parser read becomes
  `processed: false` (consolidated next cycle, like a G20 edit). An owner → agent episode Sleep has
  not read is parked (`processed: true, processed_by: parser`). **An episode Sleep already
  consolidated is relabelled and never re-queued or parked** — its claims exist either way, and
  consolidating it twice would repeat G104's defect. A tombstoned episode (`source_deleted_at`) keeps
  its stamp and follows the same queue rule. R-LS10 says an agent's words are never queued for
  Sleep, deleted file or not, and tombstoning never touched the queue. It gets no paper step, because
  its file is gone and its claims were closed when it was tombstoned. Paper why-claims follow:
  the route re-parses every moved live episode through `papers.reconcile`, which reads `authorship`
  from the frontmatter. The owner's claim closes, the agent's opens (the observer is in the id). While
  Sleep runs the folder is flagged `papers_pending` instead (R-LS17).
- **R-B8 — Stored span kinds are not rewritten.** Verified: the Reader re-derives (turn roles and an
  asserted focus read the episode's current `evidence_kind`), so it shows the new authorship at once.
  A claim's chip and `/citations` row show the kind minted with the claim. Paper claims are re-minted
  by R-B7's re-parse. Agent → owner episodes are re-consolidated by Sleep with the new override
  (`entity_extractor.py:380`). The one residual is a claim Sleep extracted from an episode that later
  moved owner → agent. It keeps its minted `user` kind and its trust, because relabelling the span
  without re-judging the belief would be half a fix. That call is the owner's (Open questions).
- **R-B9 — Harness labels are the `harness` kind, not a new `agent` value.** `_classify_author_kind`
  answers `harness` (provider `None`) for every key of `source_overview.HARNESS_LABELS` except
  `unknown`, for `agent`, and for the legacy placeholder. The app already decodes, names and marks
  `harness`; a new `agent` value would fall into its `default:` branch as a model wearing initials.
  One table means a new remote app is a harness here the day it is a card on the Sources page. A
  free-text `CICADA_SESSION_HARNESS` value outside that table stays `model` (disclosed).
- **R-B10 — The placeholder reads as `agent` everywhere, and history is never rewritten.**
  `git_service.canonical_author` maps `mcp-agentic-write` → `agent`. It is applied where a claim's
  author reaches a reader: `claim_to_model`, `entity_provenance`'s contributor count, the citations
  row, and the inbox feedback ledger's `extractor_model`. `author_identity` canonicalises too.
  `owns` keeps the legacy rule (any local agent, `mcp` origin only). The `agent` bucket now owns only
  what an unidentified MCP agent wrote (`origin: mcp`), because R-B11 makes `agent` the author of
  deterministic assistant words too. The same commits and claims now serialise differently, so the
  three ETags whose bodies carry an author kind fold `git_service.AUTHOR_SHAPE = "harness-1"` into
  their `extra`: `/contributors`, `/entities/{id}/provenance` and `/episodes/{id}/citations`.
  `/contributors` is a Store domain with an on-disk cache, and without the tag it would 304 the old
  `model` rows until the next commit. This is the `graph.NODE_SHAPE` rule. No component or client
  mapping changes, and the next body change bumps the constant.
- **R-B11 — New writes record who wrote the words.** `_ReconcileSettings.litellm_model` becomes
  `agent`, so an agentic write that names no author is an agent's. Deterministic writers pass their
  own: Telegram's reason is `user` (the person typed it; its commit is already `user`). Wispr Flow's
  to-dos are `agent` (its model's words, `assistant` spans). A folder paper claim is `who` (`user` or
  `agent`, from the file's authorship). Trailers are unchanged: agent commits already carry the
  harness label (`agent_commits.author_for`).
- **R-B12 — Paper claim words drop in-document anchors; the episode and the id keep the raw words.**
  `papers.clean_claim_text` leaves text with neither an in-document link nor a footnote marker
  byte-identical. Otherwise: `[label](#target)` keeps `label` when it is prose and drops it when it is
  a reference label (`N50`, `12`, `fn3`, `^1`) or has no letter or digit (`↩`). `[^x]` is dropped.
  Empty brackets, doubled spaces, space before punctuation and repeated `,`/`;` are tidied. External
  links are never touched. It applies to a paper claim's `text` and to a literal `object`. The
  evidence quote stays the raw note, so the span still points into the untouched episode (G118). The
  id is still minted from the raw note, so every existing id is minted again unchanged (R-FX5). A
  note that was nothing but anchors writes no `saved-because`. **Disclosed consequence:**
  `papers._same_slot` recomputes an old claim's id from its STORED object. For a note whose raw
  words had anchors, the cleaned object no longer reproduces the id, so the slot test answers
  `False`. When such a note is later edited, the old claim closes with `superseded_by: None` instead
  of naming its successor. It never names a wrong one. The raw words are not stored anywhere (spans,
  not copies), so an exact answer needs a stored slot, which is a schema change. Not in scope.
- **R-B13 — Existing claims are repaired once, in F1's shape, and on every re-read.**
  `paper_claim_text_migration.repair_paper_claim_text` uses marker `.paper_claim_text_v1` and trigger
  `maintenance/paper_claim_text`, commits as `Cicada-Author: cicada` through `commit_paths_sync`
  (R-B1), holds `folder_source._LOCK`, and is robust per page. It commits what landed, and its marker
  stays off after any failure. It is wired into `bank_migrations` after the placeholder rewrite.
  `apply_claims` also repairs a noisy claim it re-reads (R-FX6(b)'s "a sync repairs what it
  re-reads"). A claim whose words clean to nothing is left as is; the writer's next re-parse closes it.
- **R-B14 — `video` and `meetings` bridges go active; `documents` stays off.** `video`:
  `cicada_record_watch` exists (G140), saves an unsaved link first, and files the video's words as
  `media`. `meetings` (`wispr-flow`, `granola`, `transcribe`): `cicada_save_episode` stores content
  verbatim, and `speaker:<label>:` lines read as `speaker` in any episode (G134), so the line tells
  the agent to write every utterance that way, `speaker:unknown:` when it can't tell, and never
  `user:`. An agent cannot read the owner's speaker names, so crediting the owner is the one thing it
  must not guess (R-N2). The two hosted MCP entries stay `unknown` to install detection (R-O27), so
  their line appears only where detection can say "installed"; `transcribe` produces it on Codex.
  `documents` stays off: no evidence kind names a document's author, and a marker-less episode reads
  as the person's (R4), which is exactly R-O28's hazard. Arguments are plain names in the line,
  because `test_skill_catalog.py`'s R12 check splits on commas. No `CONTRACT_VERSION` bump: the
  bridge set is already in the handshake cache key.
- **R-B15 — Tunnel detection looks where installers put tunnels; it still only looks.** `reach.find_tool`
  tries `which(name)`, then `TUNNEL_BIN_DIRS = ("/opt/homebrew/bin", "/usr/local/bin", "~/bin",
  "~/.local/bin")` for an executable file, and Tailscale then the app bundle. It is reach's own list,
  not `connections.base.resolve_binary`, because detection must stay injectable (`which`, `exists`)
  so the suite never reads the machine it runs on. No `CICADA_*_CLI` override was asked for. Nothing
  is started or stopped (G135).
- **R-B16 — `next_at` is already right; pin it, don't rebuild it.** `/state` and `/status` share one
  formula with one set of inputs (Track P R6). This track adds a four-mode parity test (plus the empty
  after_import queue) and replaces TODO's stale "Disclosed gap" with the fact.

---

## File map

| File | Task | Responsibility |
|---|---|---|
| `api/services/git_service.py` | 1, 4 | `write_lock`, `WRITE_SUBCOMMANDS`, `INDEX_LOCK_BACKOFF_S`, `_spawn`, `_git_sync`, `run_git_write_sync`, `commit_paths_sync`, `commit_changes_sync`; `_run_git` routes writes and sets `GIT_OPTIONAL_LOCKS=0`; async commits wrap the sync ones (1). `AGENT_AUTHOR`, `LEGACY_AGENT_AUTHOR`, `HARNESS_KIND`, `canonical_author`, the `harness` bucket (4) |
| `api/services/{inbox,placeholder_summary,paper_context,decay,export_origin,decay_watermark}_migration.py`, `api/services/claim_expiry.py` | 1 | commit / restore through `git_service` |
| `api/services/folder_source.py` | 2, 3 | pending-commit ledger, `commit_paths_for(channel=…) -> bool`, `flush_pending_commits` (2); `reapply_authorship`, `AUTHORSHIP_TRIGGER` (3) |
| `api/services/bank_registry.py` | 2 | `git_dir` (this checkout's own git dir) |
| `api/services/sync_state.py` | 2 | `clear_error` |
| `api/services/paper_metadata.py` | 2 | channel + record only on a landed commit |
| `api/services/sleep_cycle.py` | 2 | `_flush_pending_commits_safely` at cycle start; channels on the tail's two commits |
| `api/routers/local_sources.py` | 2, 3 | channels (2); `_reapply_authorship`, the PUT and re-pick POST (3) |
| `api/services/episode_staging.py` | 3 | `reattribute` |
| `api/services/agentic_write.py`, `telegram_capture.py`, `wispr_flow.py`, `papers.py`, `transclusion_resolver.py`, `provenance.py`, `inbox_service.py` | 4 | authors at write, `canonical_author` at read, `owns` |
| `api/routers/contributors.py`, `api/routers/claims.py`, `api/routers/episodes.py` | 4 | `AUTHOR_SHAPE` folded into three ETags' `extra` (R-B10) |
| `api/services/papers.py` | 5 | `clean_claim_text`, `repair_claim_text`, cleaned words at write, repair on re-read |
| `api/services/paper_claim_text_migration.py` (new), `api/services/bank_migrations.py` | 5 | the one-shot repair |
| `api/data/recommended_skills.json`, `api/services/skill_catalog.py` | 6 | bridges, `BRIDGE_TEXT` |
| `api/remote/reach.py` | 7 | `TUNNEL_BIN_DIRS`, `find_tool`, `detect` |
| Tests (new) | 1–7 | `test_git_write_lock.py`, `test_pending_commits.py`, `test_folder_authorship_reapply.py`, `test_agent_labels.py`, `test_paper_claim_text.py`, `test_remote_reach_paths.py` |
| Tests (edited) | 2, 4, 6, 7 | `test_paper_metadata.py` (fake returns `True`), `test_wispr_flow.py` (author), `test_skill_catalog.py`, `test_handshake_bridges.py`, `test_state_wiring.py` |
| Docs | 1–7 | `CLAUDE.md`, `docs/goals/TODO.md`, `docs/goals/memory-evolution.md` (G118, G133, G135, G138) |

---

### Task 1: One git writer per bank — the lock, the retry, quiet readers, and a lint (R-B1 · R-B2 · R-B3 · R-B4)

**Files:**
- Modify: `api/services/git_service.py` (imports; new block before `_run_git`; `_run_git:403-421`;
  `commit_changes:1153-1162`; `commit_paths:1165-1178`)
- Modify: `api/services/inbox_migration.py:189-219, :297-318`,
  `api/services/placeholder_summary_migration.py:105-116`,
  `api/services/paper_context_migration.py:119-130`, `api/services/decay_migration.py:126-164`,
  `api/services/export_origin_migration.py:91-103`,
  `api/services/decay_watermark_migration.py:306-335`, `api/services/claim_expiry.py:146-157`
- Test: `api/tests/test_git_write_lock.py` (new)
- Docs: `CLAUDE.md` (Git section), `docs/goals/TODO.md` (new F2-back paragraph)

**Interfaces:**
- Produces `git_service.write_lock(memory_path) -> threading.RLock`, `WRITE_SUBCOMMANDS`,
  `INDEX_LOCK_BACKOFF_S`, `_sleep`, `_spawn(memory_path, args)`, `run_git_write_sync(memory_path,
  *args) -> str`, `commit_paths_sync(memory_path, message, paths) -> None`,
  `commit_changes_sync(memory_path, message) -> str | None`. `commit_paths` / `commit_changes` keep
  their signatures and return values.
- Consumes nothing new.

- [ ] **Step 1: Failing tests** — `api/tests/test_git_write_lock.py`:

```python
"""F2-back R-B1 … R-B4 — one git writer per bank, git's own index lock waited
out and never deleted, readers that never take it, and a lint that keeps every
mutating git command inside `git_service`."""
from __future__ import annotations

import asyncio
import os
import re
import subprocess
import threading
import time
from pathlib import Path

import pytest

from api.services import git_service

REPO = Path(__file__).resolve().parents[2]


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True).stdout


@pytest.fixture
def bank(tmp_path: Path) -> Path:
    bank = tmp_path / "bank"
    (bank / "entities").mkdir(parents=True)
    _git(bank, "init", "-q")
    _git(bank, "config", "user.email", "test@example.com")
    _git(bank, "config", "user.name", "Cicada Test")
    (bank / "seed.md").write_text("seed\n", encoding="utf-8")
    _git(bank, "add", "seed.md")
    _git(bank, "commit", "-q", "-m", "seed")
    return bank


def _message(i: int, author: str) -> str:
    return git_service.build_commit_message(
        f"Write {i}", [f"entities/page-{i}.md: updated (trigger: test)"], authors=[author])


def _write_pages(bank: Path, n: int) -> None:
    for i in range(n):
        (bank / "entities" / f"page-{i}.md").write_text(f"page {i}\n", encoding="utf-8")


def _author_of(bank: Path, rel: str) -> str:
    return _git(bank, "log", "-1", "--format=%(trailers:key=Cicada-Author,valueonly)", "--", rel).strip()


# --- R-B1 / R-B4: one writer at a time ----------------------------------------


def test_concurrent_async_writers_all_land_under_their_own_authors(bank):
    """The incident, reproduced: eight tasks on one bank failed 5 of 5 trials with
    `index.lock: File exists` and left 6–7 pages dirty for the next `git add -A`."""
    _write_pages(bank, 8)

    async def one(i):
        await git_service.commit_paths(bank, _message(i, f"writer-{i}"), [f"entities/page-{i}.md"])

    async def all_writers():
        await asyncio.gather(*(one(i) for i in range(8)))

    asyncio.run(all_writers())
    assert _git(bank, "status", "--porcelain") == ""
    for i in range(8):
        assert _author_of(bank, f"entities/page-{i}.md") == f"writer-{i}"


def test_threads_bridges_and_tasks_queue_on_the_same_lock(bank):
    """Sync callers (migrations), `asyncio.run` bridges on threads (agent commits,
    calendar polls, the demo bank) and loop tasks are all one queue."""
    _write_pages(bank, 6)
    errors: list[BaseException] = []

    def in_thread(i):
        try:
            git_service.commit_paths_sync(bank, _message(i, f"thread-{i}"), [f"entities/page-{i}.md"])
        except BaseException as exc:  # noqa: BLE001 — surfaced by the assert below
            errors.append(exc)

    def bridged(i):
        try:
            asyncio.run(git_service.commit_paths(bank, _message(i, f"bridge-{i}"), [f"entities/page-{i}.md"]))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    workers = [threading.Thread(target=in_thread, args=(i,)) for i in (0, 1)]
    workers += [threading.Thread(target=bridged, args=(i,)) for i in (2, 3)]
    for w in workers:
        w.start()

    async def tasks():
        await asyncio.gather(*(git_service.commit_paths(bank, _message(i, f"task-{i}"), [f"entities/page-{i}.md"])
                               for i in (4, 5)))

    asyncio.run(tasks())
    for w in workers:
        w.join()
    assert errors == []
    assert _git(bank, "status", "--porcelain") == ""
    assert [_author_of(bank, f"entities/page-{i}.md") for i in range(6)] == [
        "thread-0", "thread-1", "bridge-2", "bridge-3", "task-4", "task-5"]


def test_one_writers_sequence_never_interleaves_with_another(bank, monkeypatch):
    """R-B4: the lock covers add → status → commit, so a `status` check and its
    commit can never straddle another writer's `add`."""
    _write_pages(bank, 2)
    order: list[int] = []
    real = git_service._spawn

    def slow(memory_path, args):
        order.append(threading.get_ident())
        time.sleep(0.02)
        return real(memory_path, args)

    monkeypatch.setattr(git_service, "_spawn", slow)
    workers = [threading.Thread(target=git_service.commit_paths_sync,
                                args=(bank, _message(i, f"w-{i}"), [f"entities/page-{i}.md"]))
               for i in range(2)]
    for w in workers:
        w.start()
    for w in workers:
        w.join()
    assert len(order) == 6
    assert sum(1 for a, b in zip(order, order[1:]) if a != b) == 1, order
    assert _git(bank, "status", "--porcelain") == ""


def test_the_lock_is_one_per_resolved_bank(bank, tmp_path):
    alias = tmp_path / "alias"
    alias.symlink_to(bank)
    assert git_service.write_lock(bank) is git_service.write_lock(f"{bank}/")
    assert git_service.write_lock(bank) is git_service.write_lock(alias)
    assert git_service.write_lock(bank) is not git_service.write_lock(tmp_path)


def test_commit_changes_still_returns_the_new_head_or_none(bank):
    _write_pages(bank, 1)
    head = asyncio.run(git_service.commit_changes(bank, _message(0, "writer-0")))
    assert head == _git(bank, "rev-parse", "HEAD").strip()
    assert asyncio.run(git_service.commit_changes(bank, "nothing to say")) is None


# --- R-B2: another process's index lock ---------------------------------------


def test_an_external_index_lock_is_waited_out_and_never_deleted(bank, monkeypatch):
    """The owner's terminal holds the index for a moment: the writer waits, and
    the lock is removed by the process that owns it — never by Cicada."""
    _write_pages(bank, 1)
    lock = bank / ".git" / "index.lock"
    lock.write_text("", encoding="utf-8")
    waits: list[float] = []

    def the_other_git_finishes(delay):
        waits.append(delay)
        lock.unlink()

    monkeypatch.setattr(git_service, "_sleep", the_other_git_finishes)
    git_service.commit_paths_sync(bank, _message(0, "writer-0"), ["entities/page-0.md"])
    assert waits == [git_service.INDEX_LOCK_BACKOFF_S[0]]
    assert _author_of(bank, "entities/page-0.md") == "writer-0"


def test_a_lock_that_stays_fails_after_five_tries_and_is_left_in_place(bank, monkeypatch):
    _write_pages(bank, 1)
    lock = bank / ".git" / "index.lock"
    lock.write_text("", encoding="utf-8")
    waits: list[float] = []
    monkeypatch.setattr(git_service, "_sleep", waits.append)
    with pytest.raises(git_service.GitError, match="index.lock"):
        git_service.commit_paths_sync(bank, _message(0, "writer-0"), ["entities/page-0.md"])
    assert waits == list(git_service.INDEX_LOCK_BACKOFF_S), "five tries, four waits"
    assert lock.exists(), "Cicada never deletes another process's index lock"
    lock.unlink()
    # `--untracked-files=all`: the page was never added, and plain porcelain folds a
    # wholly-untracked directory into `?? entities/`.
    assert "entities/page-0.md" in _git(bank, "status", "--porcelain", "--untracked-files=all")


def test_only_the_index_lock_refusal_is_retried(bank, monkeypatch):
    waits: list[float] = []
    monkeypatch.setattr(git_service, "_sleep", waits.append)
    with pytest.raises(git_service.GitError):
        git_service.commit_paths_sync(bank, "x", ["entities/does-not-exist.md"])
    assert waits == []


# --- R-B3: readers ------------------------------------------------------------


def test_a_read_never_takes_gits_optional_index_lock(bank, monkeypatch):
    seen: dict = {}
    real = asyncio.create_subprocess_exec

    async def spy(*args, **kwargs):
        seen["env"] = kwargs.get("env")
        return await real(*args, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spy)
    asyncio.run(git_service._run_git(bank, "status", "--porcelain"))
    assert seen["env"]["GIT_OPTIONAL_LOCKS"] == "0"


def test_a_write_through_run_git_takes_the_bank_lock_and_a_read_does_not(bank, monkeypatch):
    """`inbox_service`'s `git mv` / `git rm` go through `_run_git`: they queue too."""
    calls: list[tuple] = []
    monkeypatch.setattr(git_service, "run_git_write_sync", lambda path, *args: calls.append(args) or "")
    asyncio.run(git_service._run_git(bank, "rm", "-f", "seed.md"))
    asyncio.run(git_service._run_git(bank, "log", "-1"))
    assert calls == [("rm", "-f", "seed.md")]


# --- The lint (R-B1's durable half) -------------------------------------------

_WRITE_LITERAL = re.compile(
    r"""["']git["']\s*,\s*(?:["']-C["']\s*,\s*[^,\]]+,\s*)?["']("""
    + "|".join(sorted(re.escape(s) for s in git_service.WRITE_SUBCOMMANDS))
    + r""")["']""")


def _python_files():
    for root in (REPO / "api", REPO / "mcp"):
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            dirnames[:] = [d for d in dirnames if d not in {".venv", "tests", "__pycache__"}]
            for name in filenames:
                if name.endswith(".py"):
                    yield Path(dirpath) / name


def test_the_lint_catches_what_it_is_for():
    assert _WRITE_LITERAL.search('subprocess.run(["git", "add", "--", *rel], cwd=x)')
    assert _WRITE_LITERAL.search("run(['git', '-C', str(bank), 'commit', '-m', m])")
    assert not _WRITE_LITERAL.search('subprocess.run(["git", "init"], cwd=x)')
    assert not _WRITE_LITERAL.search('subprocess.run(["git", *args], cwd=x)')


def test_no_module_spawns_a_git_write_outside_git_service():
    """A writer that spawns `git add`/`commit`/`rm`/… itself bypasses the one lock,
    as the seven migrations and the expiry restore did before this track."""
    hits = [str(p.relative_to(REPO)) for p in _python_files()
            if p.name != "git_service.py" and _WRITE_LITERAL.search(p.read_text(encoding="utf-8"))]
    assert hits == []
```

Run: `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_git_write_lock.py -q -p no:cacheprovider`
→ fails: `AttributeError: module 'api.services.git_service' has no attribute 'WRITE_SUBCOMMANDS'`
at collection (the lint's module-level regex). With that stubbed, the gather test reproduces the
incident. That is the red.

- [ ] **Step 2: `git_service.py` — the lock, the retry, the sync writers.** Imports at the top become:

```python
import asyncio
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from loguru import logger

from api.models.schemas import (
```

Insert this block immediately above `async def _run_git` (`:403`):

```python
# --- One git writer per bank (F2-back R-B1 … R-B4) ---------------------------
#
# Found in the owner's review (2026-09-23): a background paper-details commit
# failed with git's own "Unable to create '.git/index.lock': File exists"
# because a folder-sync commit was running at the same moment, and the pages it
# wrote stayed dirty for the next `git add -A` writer to sweep under its own
# author — the G85-class smear. Eight concurrent `commit_paths` on one test bank
# reproduced it in five trials out of five. So every mutating git command runs
# under ONE re-entrant lock per bank, keyed by the resolved path, and held by a
# worker thread for the whole add → status → commit sequence: a thread lock, so
# loop tasks, the threadpool, `asyncio.run` bridges on other threads and sync
# startup migrations all queue on the same object (R-B4); the whole sequence, so
# a `status` check and its commit never straddle another writer. The backend is
# one process (R-B1); across processes git's own index.lock is the guard, and
# only its "File exists" refusal is retried (R-B2).

#: Subcommands that write the index, the working tree or a ref. `_run_git`
#: routes these through the lock; `test_git_write_lock.py`'s lint refuses a
#: literal of any of them spawned anywhere else in `api/` or `mcp/`.
WRITE_SUBCOMMANDS = frozenset({
    "add", "apply", "checkout", "cherry-pick", "clean", "commit", "merge", "mv",
    "reset", "restore", "revert", "rm", "stash", "update-index",
})
#: Waits between tries while ANOTHER process holds the index (R-B2): five tries
#: in about two seconds. A terminal's `git add` takes milliseconds; an editor left
#: open by `git commit` does not, and that case is R-B5's to keep.
INDEX_LOCK_BACKOFF_S: tuple[float, ...] = (0.1, 0.25, 0.5, 1.0)
#: The retry's clock — a seam, so the suite never sleeps.
_sleep = time.sleep

_WRITE_LOCKS: dict[str, threading.RLock] = {}
_WRITE_LOCKS_GUARD = threading.Lock()


def write_lock(memory_path) -> threading.RLock:
    """The one lock every git writer of this bank holds (R-B1). Keyed by the
    resolved path, so `bank`, `bank/` and a symlink to it are one bank.
    Re-entrant: a caller already holding it may call `commit_paths_sync`."""
    key = os.path.realpath(os.fspath(memory_path))
    with _WRITE_LOCKS_GUARD:
        return _WRITE_LOCKS.setdefault(key, threading.RLock())


def _index_lock_busy(stderr: str) -> bool:
    """Git's refusal while another process holds `.git/index.lock` — the one
    failure a writer retries (R-B2)."""
    return "index.lock" in stderr and "File exists" in stderr


def _spawn(memory_path: Path, args: tuple[str, ...]) -> subprocess.CompletedProcess:
    """The one place a mutating git command starts (a test seam)."""
    return subprocess.run(["git", *args], cwd=str(memory_path), capture_output=True)


def _git_sync(memory_path: Path, *args: str) -> str:
    """One git command, called with the bank's write lock held. Retries only git's
    index-lock refusal and never deletes the lock (R-B2): another process owns
    it, and removing it under a live commit corrupts the index."""
    for delay in (*INDEX_LOCK_BACKOFF_S, None):
        try:
            proc = _spawn(memory_path, args)
        except OSError as exc:
            raise GitError(f"git {' '.join(args)} failed: {exc}") from exc
        if proc.returncode == 0:
            return proc.stdout.decode(errors="replace")
        stderr = proc.stderr.decode(errors="replace")
        if delay is None or not _index_lock_busy(stderr):
            raise GitError(f"git {' '.join(args)} failed: {stderr}")
        logger.info(f"git {args[0]}: another git process holds this bank's index — retrying in {delay}s")
        _sleep(delay)
    raise GitError(f"git {' '.join(args)} failed")  # unreachable: the last try has no delay


def run_git_write_sync(memory_path, *args: str) -> str:
    """One mutating git command under the bank's write lock (R-B1) — for a sync
    caller (the expiry restore) and for `_run_git`'s write branch."""
    memory_path = Path(memory_path)
    with write_lock(memory_path):
        return _git_sync(memory_path, *args)


def commit_paths_sync(memory_path, message: str, paths) -> None:
    """Stage and commit ONLY ``paths`` (memory-relative), never ``git add -A``,
    under the bank's write lock (R-B1, R-B4).

    A targeted write (adding a fact source, deferring one inbox item, a
    migration) must not sweep unrelated dirty files into its commit — that
    would attribute someone else's change to this action's trigger and author.
    """
    paths = [str(p) for p in paths or ()]
    if not paths:
        return
    memory_path = Path(memory_path)
    with write_lock(memory_path):
        _git_sync(memory_path, "add", "--", *paths)
        if not _git_sync(memory_path, "status", "--porcelain", "--", *paths).strip():
            return  # Nothing to commit
        _git_sync(memory_path, "commit", "-m", message, "--", *paths)


def commit_changes_sync(memory_path, message: str) -> str | None:
    """Stage all changes and commit under the bank's write lock. The new commit
    hash, or ``None`` when there was nothing to commit."""
    memory_path = Path(memory_path)
    with write_lock(memory_path):
        _git_sync(memory_path, "add", "-A")
        if not _git_sync(memory_path, "status", "--porcelain").strip():
            return None  # Nothing to commit
        _git_sync(memory_path, "commit", "-m", message)
        return _git_sync(memory_path, "rev-parse", "HEAD").strip()
```

Replace `_run_git` (`:403-421`) with:

```python
async def _run_git(memory_path: Path, *args: str) -> str:
    if args and args[0] in WRITE_SUBCOMMANDS:
        # R-B1: a write through the async helper (`inbox_service`'s `git mv` /
        # `git rm`) queues on the same lock as every commit.
        return await asyncio.to_thread(run_git_write_sync, memory_path, *args)
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=str(memory_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            # R-B3: `git status` otherwise takes the index lock to refresh its
            # stat cache — the very lock a Cicada writer then finds held.
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        )
    except OSError as exc:
        # cwd missing (e.g. a bank/memory dir not yet scaffolded) -> treat like
        # "no git history" rather than crashing the caller.
        raise GitError(f"git {' '.join(args)} failed: {exc}") from exc
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {stderr.decode(errors='replace')}")
    # ``errors="replace"`` so a non-UTF-8 entity file (porcelain blame embeds the
    # raw file bytes) degrades gracefully instead of raising a 500.
    return stdout.decode(errors="replace")
```

Replace `commit_changes` and `commit_paths` (`:1153-1178`) with:

```python
async def commit_changes(memory_path: Path, message: str) -> str | None:
    """Stage all changes and commit. Returns the new commit hash, or ``None``
    when there was nothing to commit. Runs in a worker thread under the bank's
    one write lock (R-B4)."""
    return await asyncio.to_thread(commit_changes_sync, memory_path, message)


async def commit_paths(memory_path: Path, message: str, paths: list[str]) -> None:
    """Stage and commit ONLY ``paths`` (memory-relative), never ``git add -A`` —
    :func:`commit_paths_sync` in a worker thread (R-B4)."""
    if not paths:
        return
    await asyncio.to_thread(commit_paths_sync, memory_path, message, list(paths))
```

- [ ] **Step 3: The seven direct writers go through `git_service`.** In each, drop the
`subprocess.run` calls and remove `import subprocess` when `rg -n 'subprocess\.' <file>` shows no
other use (after this step none of the seven modules, nor `claim_expiry`, has one). Every caller already catches `Exception` (`inbox_migration.py:44-52, :279-287`,
`placeholder_summary_migration.py:62`, `paper_context_migration.py:66`, `decay_migration.py:69`,
`export_origin_migration.py:60`, `decay_watermark_migration.py:162`), so a `GitError` in place of a
`CalledProcessError` changes nothing upstream.

`inbox_migration._commit_migration`:

```python
def _commit_migration(memory_path: Path, moved: int) -> None:
    """Commit the migration scoped to ONLY inbox/, nudges/, clarifications/.

    Never ``git add -A`` — concurrent unrelated changes in the working tree
    must not be swept into the migration commit. Through ``git_service`` so it
    queues on the bank's one write lock (F2-back R-B1).
    """
    message = (
        "Migrate nudges + clarifications into unified inbox/\n\n"
        f"Moved {moved} legacy items into inbox/ (trigger: migration/inbox)"
    )
    git_service.commit_paths_sync(memory_path, message, ["inbox", "nudges", "clarifications"])
```

`inbox_migration._commit_dedup`:

```python
def _commit_dedup(memory_path: Path, removed: int) -> None:
    """Commit the dedup scoped to ONLY inbox/ (never ``git add -A``), under the
    bank's write lock (F2-back R-B1)."""
    message = git_service.build_commit_message(
        "Collapse duplicate open inbox questions",
        [f"inbox/: {removed} duplicate item(s) merged into their oldest sibling (trigger: inbox/dedup)"],
        authors=["cicada"],
    )
    git_service.commit_paths_sync(memory_path, message, ["inbox"])
```

`placeholder_summary_migration._commit`:

```python
def _commit(memory_path: Path, rel: list[str]) -> None:
    message = git_service.build_commit_message(
        f"Write placeholder summaries {date.today().isoformat()}",
        [f"{p}: updated (trigger: {TRIGGER})" for p in rel],
        authors=["cicada"],
    )
    git_service.commit_paths_sync(memory_path, message, rel)  # F2-back R-B1: the bank's one write lock
```

`paper_context_migration._commit`:

```python
def _commit(memory_path: Path, rel: list[str]) -> None:
    message = git_service.build_commit_message(
        f"Repair paper contexts {date.today().isoformat()}",
        [f"{p}: updated (trigger: {TRIGGER})" for p in rel],
        authors=["cicada"],
    )
    git_service.commit_paths_sync(memory_path, message, rel)  # F2-back R-B1: the bank's one write lock
```

`decay_migration._commit_backfill`: keep its docstring, the ARG_MAX comment, the `rel` computation
and the `if not rel: return`. Replace everything from `subprocess.run(["git", "add", …` to the end
with:

```python
    message = git_service.build_commit_message(
        f"Backfill decay classes {date.today().isoformat()}",
        [
            f"entities/: {counts['media']} media page(s) -> evergreen, "
            f"{counts['skills']} skill(s) -> durable, "
            f"{counts['restored']} restored to active (trigger: {TRIGGER})"
        ],
        authors=["cicada"],
    )
    git_service.commit_paths_sync(memory_path, message, rel)  # F2-back R-B1
```

`export_origin_migration._commit`:

```python
def _commit(memory_path: Path, written: list[Path]) -> None:
    rel = [str(p.relative_to(memory_path)) for p in written]
    message = git_service.build_commit_message(
        f"Backfill export origins {date.today().isoformat()}",
        [f"episodes/: {len(rel)} chat-export episode(s) stamped with their origin (trigger: {TRIGGER})"],
        authors=["cicada"],
    )
    git_service.commit_paths_sync(memory_path, message, rel)  # F2-back R-B1
```

`decay_watermark_migration._commit_backfill`: keep the docstring and `if not rel: return`, then:

```python
    message = git_service.build_commit_message(
        f"Backfill decay watermarks {date.today().isoformat()}",
        [
            f"entities/: {counts['entities']} page(s) + {counts['claims']} open claim(s) "
            f"stamped decayed_through (trigger: {TRIGGER})"
        ],
        authors=["cicada"],
    )
    git_service.commit_paths_sync(memory_path, message, rel)  # F2-back R-B1
```

`claim_expiry.restore` becomes (the docstring's first three lines are today's, one sentence added;
it is called through `asyncio.to_thread` at `sleep_cycle.py:814`, so waiting on the lock never
blocks the loop):

```python
def restore(memory_path: Path, paths: list[str]) -> None:
    """Put pages back as HEAD has them after a failed expiry commit (Q-R7).
    The expiry is re-derived tomorrow; a page left dirty would be stamped by
    the next ``git add -A`` writer under the wrong author — the G85 smear.
    Through the bank's one write lock, like every git write (F2-back R-B1)."""
    if not paths or not (Path(memory_path) / ".git").exists():
        return
    try:
        git_service.run_git_write_sync(memory_path, "checkout", "--", *paths)
    except git_service.GitError as exc:
        logger.warning(f"expiry restore failed: {type(exc).__name__}")
```

`inbox_service._git_move` / `_git_remove` need no edit: `_run_git`'s write branch takes the lock.
`agent_commits`, `calendar_registry` and `demo_bank` need none either: their `asyncio.run` bridges now
reach `commit_paths_sync` through `to_thread`.

- [ ] **Step 4: Green.** `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_git_write_lock.py api/tests/test_claim_expiry.py api/tests/test_inbox_dedup_migration.py api/tests/test_placeholder_summary_migration.py api/tests/test_paper_context_migration.py api/tests/test_decay_migration.py api/tests/test_export_origin_migration.py api/tests/test_decay_watermark_migration.py api/tests/test_agent_provenance.py api/tests/test_session_trailer.py api/tests/test_sleep_control.py api/tests/test_sync.py api/tests/test_sleep_debt.py api/tests/test_agent_write_commits.py api/tests/test_calendar_registry.py api/tests/test_demo_bank.py -q -p no:cacheprovider`
→ 0 failures (the order-dependent provenance case: see Global Constraints). The last three cover
the `asyncio.run` bridges (`agent_commits`, `calendar_registry`, `demo_bank`), which now reach the
lock through `to_thread`.

- [ ] **Step 5: Docs.** `CLAUDE.md`, in "Git — versioning and provenance", insert after the G85
paragraph (the one ending "…fixing it needs hunk-level staging."):

```markdown
**One git writer per bank (F2-back R-B1 … R-B4).** Every mutating git command — `git_service`'s
commits, a `_run_git` write, the one-shot migrations, the expiry restore — runs in a worker thread
under one re-entrant lock per resolved bank path, so tasks, threads and `asyncio.run` bridges queue
instead of colliding on `index.lock`; the backend is one process, git's own lock is the cross-process
guard, and only its `File exists` refusal is retried (five tries, the lock never deleted). Reads pass
`GIT_OPTIONAL_LOCKS=0`, and `test_git_write_lock.py` refuses a git write spawned anywhere else.
```

`docs/goals/TODO.md`, insert after the Track F1 paragraph (the one ending "…replace with the merged
numbers."):

```markdown
**Round 3 · Track F2-back — backend fixes, batch 2 (2026-09-23, `fix/backend-batch-2`, plan
`docs/superpowers/plans/2026-09-23-backend-batch-2.md`).**
- One git writer per bank: every mutating git command queues on one per-bank lock, another
  process's `index.lock` is waited out and never deleted, readers never take it, and a lint keeps
  it that way (R-B1 … R-B4).
```

- [ ] **Step 6: Full suite, then commit.** `cd <worktree> && api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider` → 0 failures.

```bash
cd <worktree> && git add api/services/git_service.py api/services/inbox_migration.py \
  api/services/placeholder_summary_migration.py api/services/paper_context_migration.py \
  api/services/decay_migration.py api/services/export_origin_migration.py \
  api/services/decay_watermark_migration.py api/services/claim_expiry.py \
  api/tests/test_git_write_lock.py CLAUDE.md docs/goals/TODO.md
git commit -m "fix(git): one write lock per bank, index.lock waited out, quiet readers (R-B1…R-B4, G85)

Two writers committing at once collided on git's index.lock and left the loser's
pages dirty for the next git add -A writer (reproduced 5/5 with eight tasks).
Every mutating git command now runs in a worker thread under one re-entrant lock
per resolved bank path; only git's 'File exists' refusal is retried and the lock
is never deleted; reads pass GIT_OPTIONAL_LOCKS=0; the seven direct-subprocess
writers go through git_service and a lint keeps new ones out.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: A failed folder, paper or Wispr commit is kept, said, and landed later (R-B5)

**Files:**
- Modify: `api/services/folder_source.py` (new ledger block above `commit_paths_for`;
  `commit_paths_for:494-510`; new `flush_pending_commits`)
- Modify: `api/services/bank_registry.py` (new `git_dir` after `_git_dir:96-125`)
- Modify: `api/services/sync_state.py` (new `clear_error` after `record_error`)
- Modify: `api/services/paper_metadata.py:458-482` (`run_locked`'s `finally`)
- Modify: `api/services/sleep_cycle.py` (new `_flush_pending_commits_safely`; `run:906-1021`;
  `:496-497`, `:525-526`)
- Modify: `api/routers/local_sources.py:63, :75, :85, :158, :177, :206` (channels)
- Modify: `api/tests/test_paper_metadata.py:260-261` (the fake returns `True`)
- Test: `api/tests/test_pending_commits.py` (new)
- Docs: `CLAUDE.md` (the Task 1 paragraph), `docs/goals/TODO.md`

**Interfaces:**
- Produces `folder_source.PENDING_COMMITS_FILENAME`, `COMMIT_FAILED_MESSAGE`,
  `pending_commits(memory_path) -> dict[str, dict]`,
  `_update_pending(memory_path, key, *, add=(), drop=(), meta=None)` (private; the test pins it),
  `commit_paths_for(memory_path, paths, *, subject, trigger, author="user", channel=None) -> bool`,
  `flush_pending_commits(memory_path) -> int`; `bank_registry.git_dir(path) -> Path | None` (this
  checkout's own git dir, never the common dir); `sync_state.clear_error(memory_path, channel,
  error) -> None`.
- Consumes Task 1's `git_service.commit_paths` (lock + retry).

- [ ] **Step 1: Failing tests** — `api/tests/test_pending_commits.py`:

```python
"""F2-back R-B5 — a folder, paper or Wispr commit that git refuses keeps its
paths, says so on its channel, and lands on the same writer's next run (or at
the start of the next Sleep cycle) under its own author."""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from api.services import folder_source as fs, git_service, sync_state


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True).stdout


@pytest.fixture
def bank(tmp_path, monkeypatch):
    bank = tmp_path / "bank"
    for sub in ("entities", "episodes", "sources"):
        (bank / sub).mkdir(parents=True)
    _git(bank, "init", "-q")
    _git(bank, "config", "user.email", "test@example.com")
    _git(bank, "config", "user.name", "Cicada Test")
    (bank / "seed.md").write_text("seed\n", encoding="utf-8")
    _git(bank, "add", "seed.md")
    _git(bank, "commit", "-q", "-m", "seed")
    monkeypatch.setattr(git_service, "_sleep", lambda _delay: None)
    return bank


def _page(bank: Path, stem: str) -> str:
    (bank / "entities" / f"{stem}.md").write_text(f"{stem}\n", encoding="utf-8")
    return f"entities/{stem}.md"


def _papers_commit(bank: Path, paths: list[str]) -> bool:
    return asyncio.run(fs.commit_paths_for(bank, paths, subject="Paper details", trigger="papers/metadata",
                                           author="cicada", channel="papers"))


def _fail_once(bank: Path, rel: str) -> None:
    lock = bank / ".git" / "index.lock"
    lock.write_text("", encoding="utf-8")
    assert _papers_commit(bank, [rel]) is False
    lock.unlink()  # the other process finishes; it removes its own lock


def test_a_refused_commit_keeps_its_paths_and_says_so(bank):
    rel = _page(bank, "media-arxiv-2401-00001")
    lock = bank / ".git" / "index.lock"
    lock.write_text("", encoding="utf-8")
    assert _papers_commit(bank, [rel]) is False
    assert lock.exists()
    (entry,) = fs.pending_commits(bank).values()
    assert entry["paths"] == [rel]
    assert (entry["trigger"], entry["author"], entry["channel"]) == ("papers/metadata", "cicada", "papers")
    assert sync_state.read_sync_state(bank)["papers"]["last_error"] == fs.COMMIT_FAILED_MESSAGE


def test_the_ledger_lives_in_the_git_dir_never_in_the_tree(bank):
    _fail_once(bank, _page(bank, "media-arxiv-2401-00001"))
    assert (bank / ".git" / fs.PENDING_COMMITS_FILENAME).is_file()
    assert fs.PENDING_COMMITS_FILENAME not in _git(bank, "status", "--porcelain", "--untracked-files=all")


def test_the_same_writers_next_run_lands_them_under_its_own_author(bank):
    kept = _page(bank, "media-arxiv-2401-00001")
    _fail_once(bank, kept)
    fresh = _page(bank, "media-arxiv-2401-00002")
    assert _papers_commit(bank, [fresh]) is True
    assert fs.pending_commits(bank) == {}
    # Scoped to `entities`: `record_error` / `clear_error` write `sync_state.json` in
    # the bank root, which this fixture never committed (it shows as `??`).
    assert _git(bank, "status", "--porcelain", "--", "entities") == ""
    body = _git(bank, "log", "-1", "--format=%B")
    assert "Cicada-Author: cicada" in body and kept in body and fresh in body
    assert "last_error" not in sync_state.read_sync_state(bank)["papers"]


def test_another_writer_never_takes_them(bank):
    kept = _page(bank, "media-arxiv-2401-00001")
    _fail_once(bank, kept)
    mine = _page(bank, "alpha-project")
    assert asyncio.run(fs.commit_paths_for(bank, [mine], subject="Folder sync (alpha-project)",
                                           trigger="folder/sync", author="user",
                                           channel="folder:alpha-project-abc123")) is True
    assert kept in _git(bank, "status", "--porcelain")
    assert [e["paths"] for e in fs.pending_commits(bank).values()] == [[kept]]


def test_overlapping_runs_of_one_writer_never_erase_each_others_kept_paths(bank):
    """R-B5: the ledger is edited by path. A run that lands drops only what it
    committed; a path another run of the same writer kept stays kept."""
    first = _page(bank, "media-arxiv-2401-00001")
    second = _page(bank, "media-arxiv-2401-00002")
    key = "papers/metadata|cicada|papers"
    fs._update_pending(bank, key, add=[first, second],
                       meta={"subject": "Paper details", "trigger": "papers/metadata",
                             "author": "cicada", "channel": "papers"})
    fs._update_pending(bank, key, drop=[first])
    assert fs.pending_commits(bank)[key]["paths"] == [second]
    fs._update_pending(bank, key, drop=[second])
    assert fs.pending_commits(bank) == {}
    assert not (bank / ".git" / fs.PENDING_COMMITS_FILENAME).exists()


def test_a_worktree_banks_ledger_is_its_own_not_the_common_dirs(tmp_path):
    """`bank_registry.git_dir` is this checkout's git dir, never the common dir
    `_git_dir` follows for `info/exclude`: two worktree banks share that one."""
    from api.services import bank_registry

    main = tmp_path / "main"
    main.mkdir()
    _git(main, "init", "-q")
    _git(main, "config", "user.email", "test@example.com")
    _git(main, "config", "user.name", "Cicada Test")
    (main / "seed.md").write_text("seed\n", encoding="utf-8")
    _git(main, "add", "seed.md")
    _git(main, "commit", "-q", "-m", "seed")
    _git(main, "worktree", "add", "-q", str(tmp_path / "other"))
    own = bank_registry.git_dir(tmp_path / "other")
    assert own is not None and own != bank_registry.git_dir(main)
    assert own.parent.name == "worktrees", own


def test_a_flush_lands_every_kept_writer_under_its_own_author(bank):
    _fail_once(bank, _page(bank, "media-arxiv-2401-00001"))
    assert asyncio.run(fs.flush_pending_commits(bank)) == 1
    assert "Cicada-Author: cicada" in _git(bank, "log", "-1", "--format=%B")
    assert fs.pending_commits(bank) == {}


def test_a_sleep_cycle_flushes_before_any_stage_writes(monkeypatch, tmp_path):
    """`_finalize`'s `git add -A` is the sweeper this exists to beat."""
    from api.services import sleep_cycle

    order: list[str] = []

    async def flush(memory_path):
        order.append("flush")
        return 0

    async def stages(*_a, **_k):
        order.append("stages")
        return sleep_cycle._StageOutcome()

    async def tail(*_a, **_k):
        order.append("tail")

    monkeypatch.setattr(fs, "flush_pending_commits", flush)
    monkeypatch.setattr(sleep_cycle, "_run_stages", stages)
    monkeypatch.setattr(sleep_cycle, "_run_engine_independent_tail", tail)
    asyncio.run(sleep_cycle.run(SimpleNamespace(memory_path=tmp_path), "cycle-f2b"))
    assert order == ["flush", "stages", "tail"]


def test_a_bank_without_its_own_git_commits_and_records_nothing(tmp_path):
    bank = tmp_path / "plain"
    (bank / "entities").mkdir(parents=True)
    assert _papers_commit(bank, [_page(bank, "alpha-project")]) is True
    assert fs.pending_commits(bank) == {}
    assert sync_state.read_sync_state(bank) == {}


def test_a_paper_run_whose_commit_failed_never_stamps_success(bank, monkeypatch):
    from api.services import paper_metadata as pm

    async def refused(memory_path, paths, **kw):
        sync_state.record_error(memory_path, kw["channel"], fs.COMMIT_FAILED_MESSAGE)
        return False

    async def resolve(memory_path, *, report, **kw):
        report["resolved"] = 1

    monkeypatch.setattr(fs, "commit_paths_for", refused)
    monkeypatch.setattr(pm, "resolve", resolve)
    asyncio.run(pm.run_locked(bank))
    assert sync_state.read_sync_state(bank)["papers"]["last_error"] == fs.COMMIT_FAILED_MESSAGE


def test_clear_error_drops_only_the_error_it_names(tmp_path):
    sync_state.record_error(tmp_path, "papers", "Crossref HTTP 503")
    sync_state.clear_error(tmp_path, "papers", fs.COMMIT_FAILED_MESSAGE)
    assert sync_state.read_sync_state(tmp_path)["papers"]["last_error"] == "Crossref HTTP 503"
    sync_state.record_error(tmp_path, "papers", fs.COMMIT_FAILED_MESSAGE)
    sync_state.clear_error(tmp_path, "papers", fs.COMMIT_FAILED_MESSAGE)
    assert "last_error" not in sync_state.read_sync_state(tmp_path)["papers"]
```

Run it → fails on `fs.PENDING_COMMITS_FILENAME` / the `channel` keyword. That is the red.

- [ ] **Step 2: `bank_registry.git_dir`.** After `_git_dir`. It is NOT a public alias of
`_git_dir`, because that one follows a worktree's `commondir` (right for `info/exclude`, shared by
every worktree) and the ledger must be per checkout:

```python
def git_dir(path: Path) -> Path | None:
    """This checkout's OWN git dir, or None: ``<bank>/.git``, or the ``gitdir:``
    target of a worktree's or submodule's ``.git`` file — never the common dir
    :func:`_git_dir` follows for ``info/exclude``. The pending-commit ledger
    (F2-back R-B5) is per checkout: two worktree banks share one common dir,
    and one bank's kept paths must never be committed by the other's writer.
    It lives in a git dir for the reason ``info/exclude`` does (G136 R2): a
    file in the tree is swept into the next ``git add -A`` commit under the
    wrong author."""
    dot = Path(path) / ".git"
    if dot.is_dir():
        return dot
    # Same decoding guard as `_git_dir` (S-back final review): git writes bytes.
    try:
        head = dot.read_text(encoding="utf-8", errors="surrogateescape").strip() if dot.is_file() else ""
        if not head.startswith("gitdir:"):
            return None
        own = (dot.parent / head[len("gitdir:"):].strip()).resolve()
    except (OSError, UnicodeError, ValueError):
        return None
    return own if own.is_dir() else None
```

- [ ] **Step 3: `sync_state.clear_error`.** After `record_error`:

```python
def clear_error(memory_path: Path, channel: str, error: str) -> None:
    """Drop ``channel``'s ``last_error`` only while it still reads ``error``:
    the failure a later success of the same kind fixed (F2-back R-B5, a kept
    commit that has now landed). Any other error stays, and so does the rest of
    the entry — its last success included."""
    state = read_sync_state(memory_path)
    entry = state.get(channel)
    if not isinstance(entry, dict) or entry.get("last_error") != error:
        return
    entry = dict(entry)
    entry.pop("last_error", None)
    entry.pop("last_error_at", None)
    state[channel] = entry
    _write_state(memory_path, state)
```

- [ ] **Step 4: `folder_source` — the ledger, the commit, the flush.** Replace the
`# --- Commits (R-LS30) ---` section (`:491-510`) with:

```python
# --- Commits (R-LS30, F2-back R-B5) -----------------------------------------

#: The commits git refused, kept in the bank's own git dir — never in the tree,
#: where the ledger would be swept into the next `git add -A` commit (G136 R2).
PENDING_COMMITS_FILENAME = "cicada-pending-commits.json"
#: What a folder, paper or Wispr card says while its save waits (R-B5). Plain
#: words; the Sources card shows the first clause.
COMMIT_FAILED_MESSAGE = ("Couldn't save the latest changes to your memory's history. "
                         "Cicada will try again on the next sync.")
MAX_PENDING_PATHS = 5000
_PENDING_LOCK = threading.Lock()


def _pending_file(memory_path: Path) -> Path | None:
    from api.services import bank_registry

    git_dir = bank_registry.git_dir(Path(memory_path))
    return None if git_dir is None else git_dir / PENDING_COMMITS_FILENAME


def pending_commits(memory_path: Path) -> dict[str, dict]:
    """``{writer key: {paths, since, subject, trigger, author, channel}}`` — the
    commits still waiting. ``{}`` for a bank without git, or when none wait."""
    path = _pending_file(memory_path)
    if path is None:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else {}


def _update_pending(memory_path: Path, key: str, *, add=(), drop=(), meta: dict | None = None) -> None:
    """Edit one writer's entry BY PATH (R-B5): ``drop`` what just landed (or
    whose file is gone), ``add`` what must still land. Never a whole-entry
    set or clear: the watcher's batch and a manual Sync of one folder are two
    runs of one writer, and a run that lands must not erase the paths the
    other has just written ahead. An entry with no paths left is removed, and
    the file with the last entry."""
    path = _pending_file(memory_path)
    if path is None:
        return
    with _PENDING_LOCK:
        data = pending_commits(memory_path)
        entry = dict(data.get(key) or {})
        gone = set(drop)
        paths = sorted({*(p for p in entry.get("paths") or [] if p not in gone), *add})[:MAX_PENDING_PATHS]
        if paths:
            data[key] = {**entry, **(meta or {}), "paths": paths,
                         "since": entry.get("since") or episode_ids.utc_now_iso()}
        elif key in data:
            data.pop(key)
        else:
            return
        if not data:
            path.unlink(missing_ok=True)
            return
        tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(path)


async def commit_paths_for(memory_path: Path, paths: list[str], *, subject: str, trigger: str,
                           author: str = "user", channel: str | None = None) -> bool:
    """A commit scoped to exactly ``paths`` — never ``git add -A`` (R-LS30) — plus
    whatever this same writer could not commit last time (F2-back R-B5).

    ``True`` when nothing is left to commit: it landed, nothing moved, or the
    bank has no ``.git`` of its own (most unit tests — and ``git`` would climb
    into an enclosing repo, the ``agent_commits`` refusal). ``False`` when git
    still refused after R-B2's retries. Then the paths stay in the ledger under
    this writer's key, and ``channel`` (when given) records
    :data:`COMMIT_FAILED_MESSAGE`, so the failure surfaces instead of the pages
    riding the next ``git add -A`` writer's commit under its author — the
    paper-details incident of the owner's 2026-09-23 review."""
    from api.services import git_service, sync_state

    memory_path = Path(memory_path)
    if _pending_file(memory_path) is None:
        return True
    key = f"{trigger}|{author}|{channel or ''}"
    kept = [p for p in (pending_commits(memory_path).get(key) or {}).get("paths") or [] if p]
    # A kept path whose file is gone is dropped: `git add` of an untracked
    # missing path fails, and it would fail every later run too.
    gone = [p for p in kept if not (memory_path / p).exists()]
    rels = sorted({p for p in [*paths, *kept] if p and p not in gone})
    if not rels:
        _update_pending(memory_path, key, drop=gone)
        return True
    lines = [f"{p}: updated (trigger: {trigger})" for p in rels[:200]]
    if len(rels) > 200:
        lines.append(f"… and {len(rels) - 200} more (trigger: {trigger})")
    message = git_service.build_commit_message(subject, lines, authors=[author])
    meta = {"subject": subject, "trigger": trigger, "author": author, "channel": channel}
    # Written ahead of the commit (the `.decay_watermarked.pending` shape): a
    # crash mid-commit still leaves the next run a list to finish.
    _update_pending(memory_path, key, add=rels, drop=gone, meta=meta)
    try:
        await git_service.commit_paths(memory_path, message, rels)
    except Exception as e:  # noqa: BLE001 - kept and said, never raised into a sync
        logger.warning(f"{trigger} commit refused — {len(rels)} path(s) kept for its next run: "
                       f"{type(e).__name__}: {e}")
        # Again, not only ahead: an overlapping run of this writer that landed
        # meanwhile dropped the paths it committed, and these must stay kept.
        _update_pending(memory_path, key, add=rels, meta=meta)
        if channel:
            sync_state.record_error(memory_path, channel, COMMIT_FAILED_MESSAGE)
        return False
    _update_pending(memory_path, key, drop=rels)
    if channel:
        sync_state.clear_error(memory_path, channel, COMMIT_FAILED_MESSAGE)
    return True


async def flush_pending_commits(memory_path: Path) -> int:
    """Commit every kept writer's paths under that writer's own subject, trigger
    and author (R-B5). ``sleep_cycle.run`` calls it before any stage writes, so
    ``_finalize``'s ``git add -A`` never sweeps them under the cycle's model.
    Returns how many writers landed. Never raises."""
    landed = 0
    for key, entry in pending_commits(memory_path).items():
        try:
            ok = await commit_paths_for(
                memory_path, [], subject=str(entry.get("subject") or "Saved changes"),
                trigger=str(entry.get("trigger") or key.split("|", 1)[0]),
                author=str(entry.get("author") or "cicada"), channel=entry.get("channel") or None)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"kept commit not landed: {type(e).__name__}")
            continue
        landed += int(ok)
    return landed
```

- [ ] **Step 5: Callers.** `paper_metadata.run_locked`'s `finally` becomes:

```python
    finally:
        # T4 review round 1, finding 2: whatever was written is committed as `cicada` and the
        # outcome recorded even when the run raised — a page left dirty here would ride the next
        # `git add -A` writer's commit under its author (the G85-class smear). F2-back R-B5: a
        # refused commit already said so on the `papers` line; a success stamp would erase it.
        try:
            committed = await folder_source.commit_paths_for(
                memory_path, report["paths"], subject="Paper details", trigger="papers/metadata",
                author="cicada", channel="papers")
            if committed:
                try:
                    record(memory_path, report)
                except Exception as e:  # noqa: BLE001 - a status line never outranks the commit
                    logger.warning(f"paper details: outcome not recorded: {type(e).__name__}")
        finally:
            _run_lock.release()
```

`test_paper_metadata.py:260-261`: the fake becomes

```python
    async def fake_commit(memory_path, paths, **kw):
        committed.append((list(paths), kw["author"], kw["trigger"]))
        return True
```

`routers/local_sources.py` — add `channel=` to each `commit_paths_for` call. `register_folder`'s
commit (`:62-63`): `channel=folder_source.channel_id(folder["id"])`. `update_folder`'s (`:74-76`) and
`sync_folder`'s (`:157-158`): `channel=folder_source.channel_id(folder_id)`. `remove_folder`'s
(`:84-86`) gets no channel, because the folder and its card are gone. `put_wispr_settings` (`:176-178`)
and `capture_wispr_flow` (`:206-207`): `channel=wispr_flow.CHANNEL_ID` (`wispr_flow` is already
imported at the top of the router).

`sleep_cycle.py` — `_resolve_papers_safely`'s `commit_paths_for` (`:496-497`) gains
`channel="papers"`. `_replay_wispr_todos_safely`'s (`:525-526`) gains `channel=wispr_flow.CHANNEL_ID`
(its local import already reads `from api.services import folder_source, wispr_flow`). Add above `run`:

```python
async def _flush_pending_commits_safely(memory_path: Path) -> None:
    """F2-back R-B5: land the folder, paper and Wispr commits git refused, under
    their own authors, BEFORE any stage writes — `_finalize`'s `git add -A` is
    the writer that would otherwise sweep them under this cycle's model (the
    G85 smear). Deterministic; never fatal."""
    try:
        from api.services import folder_source

        landed = await folder_source.flush_pending_commits(memory_path)
        if landed:
            logger.info(f"Landed {landed} kept commit(s) before the cycle")
    except Exception as e:
        logger.warning(f"Kept commits not landed: {type(e).__name__}: {e}")
```

and in `run`, make the flush the first line inside the existing `try` (before
`with agent_engine.use_scope(...)`), so a failure there can never strand `status` at `running`:

```python
    try:
        await _flush_pending_commits_safely(memory_path)
        with agent_engine.use_scope(f"sleep:{cycle_id}"):
```

- [ ] **Step 6: Green.** `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_pending_commits.py api/tests/test_paper_metadata.py api/tests/test_folder_source.py api/tests/test_papers.py api/tests/test_wispr_flow.py api/tests/test_sleep_control.py api/tests/test_sleep_resumable.py -q -p no:cacheprovider` → 0 failures.

- [ ] **Step 7: Docs.** Append to the CLAUDE.md paragraph Task 1 added:

```markdown
A folder, paper or Wispr commit that still fails keeps its paths in `cicada-pending-commits.json`
in the bank's own git dir (a worktree's, never the shared common dir), says so on its channel, and
lands on that writer's next run — or at the start of the next Sleep cycle, before any stage writes —
under its own author (R-B5).
```

TODO F2-back list, append:

```markdown
- A folder, paper or Wispr commit git still refuses is kept, said on its channel, and landed by
  the writer's next run or the next Sleep cycle's start under its own author (R-B5).
```

- [ ] **Step 8: Full suite, then commit.**

```bash
cd <worktree> && git add api/services/folder_source.py api/services/bank_registry.py \
  api/services/sync_state.py api/services/paper_metadata.py api/services/sleep_cycle.py \
  api/routers/local_sources.py api/tests/test_pending_commits.py api/tests/test_paper_metadata.py \
  CLAUDE.md docs/goals/TODO.md
git commit -m "fix(folders): a refused commit is kept, said, and landed under its author (R-B5, G85)

commit_paths_for only logged a failed commit, so a paper-details run left its
pages dirty for the next git add -A writer. It now keeps the paths in a
write-ahead ledger in the bank's git dir keyed by trigger|author|channel, records
the failure on the channel, retries on the writer's next run, and Sleep lands
every kept commit before any stage writes.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Saving authorship rules re-derives the folder's episodes in place (R-B6 · R-B7 · R-B8)

**Files:**
- Modify: `api/services/episode_staging.py` (new `reattribute` after `_requeue_for_authorship:325-341`)
- Modify: `api/services/folder_source.py` (module docstring's "Authorship (R-F2)" paragraph;
  `AUTHORSHIP_TRIGGER`; new `reapply_authorship` after `live_file_count`)
- Modify: `api/routers/local_sources.py:43-77` (`register_folder`, `update_folder`, new helper)
- Test: `api/tests/test_folder_authorship_reapply.py` (new)
- Docs: `CLAUDE.md` (the local-source rail), `docs/goals/TODO.md`, `docs/goals/memory-evolution.md` (G133)

**Interfaces:**
- Produces `episode_staging.reattribute(path, *, extra, queue_for_sleep) -> bool`;
  `folder_source.AUTHORSHIP_TRIGGER = "folder/authorship"`;
  `folder_source.reapply_authorship(memory_path, folder_id) -> {"paths", "touched", "to_owner", "to_agent"}`.
- Consumes `_requeue_for_authorship`, `authorship_for`, `_by_relpath`, `papers.reconcile`, Task 2's
  `commit_paths_for(channel=…)`.

- [ ] **Step 1: Failing tests** — `api/tests/test_folder_authorship_reapply.py`:

```python
"""F2-back R-B6 … R-B8 — a changed authorship rule re-derives the folder's
existing episodes in place, with no re-post from the app: same bytes, same hash,
the stager's own queue rule, one `user` commit."""
from __future__ import annotations

import base64
import hashlib
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import bank_index, evidence, folder_source as fs, git_service, markdown_parser, provenance
from api.services.claims import parse_claims

REFS = "## Retrieval\n\n- [Paper Alpha](https://arxiv.org/abs/2401.00001) — the architecture alpha-project builds on\n"
ALPHA = "media-arxiv-2401-00001"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True).stdout


def _file(rel, text, mtime=1_756_000_000.0):
    raw = text.encode("utf-8")
    return fs.IncomingFile(rel, mtime, hashlib.sha256(raw).hexdigest(), base64.b64encode(raw).decode())


def _body(files):
    return {"files": [{"relpath": f.relpath, "mtime": f.mtime, "sha256": f.sha256, "contentB64": f.content_b64}
                      for f in files], "deleted": []}


@pytest.fixture
def bank(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (memory / sub).mkdir(parents=True)
    _git(memory, "init", "-q")
    _git(memory, "config", "user.email", "test@example.com")
    _git(memory, "config", "user.name", "Cicada Test")
    monkeypatch.setattr(git_service, "_sleep", lambda _d: None)
    return memory


@pytest.fixture
def client(bank, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    yield TestClient(main.app)
    config.get_settings.cache_clear()


def _folder(bank):
    return fs.register(bank, label="alpha-project", path="/Users/example/alpha-project", device="mac-1")


def _episode(bank, folder, rel):
    bank_index.invalidate()
    sid = f"folder:{folder['id']}:{rel}"
    for path in (bank / "episodes").glob("ep_*.md"):
        parsed = markdown_parser.parse(path)
        if parsed.frontmatter.get("source_id") == sid:
            return path, parsed
    raise AssertionError(sid)


def _stage(bank, folder, *files):
    fs.sync(bank, folder, list(files), [])
    _git(bank, "add", "-A")
    _git(bank, "commit", "-q", "-m", "staged")


# --- the rule, unit by unit (R-B6, R-B7) -------------------------------------


def test_an_agent_file_becomes_the_owners_and_is_queued(bank):
    folder = _folder(bank)
    _stage(bank, folder, _file("archive/sweep.md", "A sweep about alpha-project."))
    path, before = _episode(bank, folder, "archive/sweep.md")
    assert (before.frontmatter["evidence_kind"], before.frontmatter["processed"]) == ("assistant", True)
    fs.update(bank, folder["id"], authorship=[])
    out = fs.reapply_authorship(bank, folder["id"])
    _, after = _episode(bank, folder, "archive/sweep.md")
    fm = after.frontmatter
    assert (fm["authorship"], fm["evidence_kind"], fm["processed"]) == ("user", "user", False)
    assert "processed_by" not in fm
    assert fm["content_hash"] == before.frontmatter["content_hash"]
    assert after.body == before.body and evidence.body_hash(after.body) == evidence.body_hash(before.body)
    assert (out["to_owner"], out["to_agent"], out["paths"]) == (1, 0, [f"episodes/{path.name}"])


def test_an_unread_owner_file_becomes_the_agents_and_is_parked(bank):
    folder = _folder(bank)
    _stage(bank, folder, _file("notes.md", "My notes on alpha-project."))
    fs.update(bank, folder["id"], authorship=[{"glob": "notes.md", "authorship": "agent"}])
    fs.reapply_authorship(bank, folder["id"])
    fm = _episode(bank, folder, "notes.md")[1].frontmatter
    assert (fm["authorship"], fm["evidence_kind"], fm["processed"], fm["processed_by"]) == (
        "agent", "assistant", True, "parser")


def test_what_sleep_already_read_is_relabelled_and_never_requeued_or_parked(bank):
    """R-B7 / G104: its claims exist either way; consolidating it twice repeats G104's defect."""
    folder = _folder(bank)
    _stage(bank, folder, _file("notes.md", "My notes on alpha-project."))
    path, parsed = _episode(bank, folder, "notes.md")
    markdown_parser.write(path, {**parsed.frontmatter, "processed": True, "processed_by": "sleep"}, parsed.body)
    fs.update(bank, folder["id"], authorship=[{"glob": "notes.md", "authorship": "agent"}])
    fs.reapply_authorship(bank, folder["id"])
    fm = _episode(bank, folder, "notes.md")[1].frontmatter
    assert (fm["evidence_kind"], fm["processed"], fm["processed_by"]) == ("assistant", True, "sleep")
    fs.update(bank, folder["id"], authorship=[])
    fs.reapply_authorship(bank, folder["id"])
    fm = _episode(bank, folder, "notes.md")[1].frontmatter
    assert (fm["evidence_kind"], fm["processed"], fm["processed_by"]) == ("user", True, "sleep")


def test_a_deleted_files_episode_follows_the_rule_and_stays_deleted(bank):
    """R-B7: a tombstone keeps its stamp, but the queue rule still holds — an
    agent's words are never queued for Sleep (R-LS10), deleted file or not; no
    paper step runs for a file that is gone."""
    folder = _folder(bank)
    _stage(bank, folder, _file("notes.md", "My notes on alpha-project."))
    fs.sync(bank, folder, [], ["notes.md"])
    before = _episode(bank, folder, "notes.md")[1].frontmatter
    assert before["processed"] is False
    fs.update(bank, folder["id"], authorship=[{"glob": "notes.md", "authorship": "agent"}])
    out = fs.reapply_authorship(bank, folder["id"])
    fm = _episode(bank, folder, "notes.md")[1].frontmatter
    assert fm["evidence_kind"] == "assistant" and fm["source_deleted_at"] == before["source_deleted_at"]
    assert (fm["processed"], fm["processed_by"]) == (True, "parser")
    assert out["to_agent"] == 1 and out["touched"] == {}


def test_a_second_pass_changes_nothing(bank):
    folder = _folder(bank)
    _stage(bank, folder, _file("archive/sweep.md", "A sweep."))
    fs.update(bank, folder["id"], authorship=[])
    fs.reapply_authorship(bank, folder["id"])
    assert fs.reapply_authorship(bank, folder["id"]) == {"paths": [], "touched": {}, "to_owner": 0, "to_agent": 0}


def test_the_reader_reads_the_new_rule_and_every_span_stays_current(bank):
    """R-B8, verified: `/episodes/{id}/text` re-derives each turn's role and an
    asserted focus's kind from the episode's current `evidence_kind`, and the
    span minted before the flip is still `current` — nothing it points at moved."""
    folder = _folder(bank)
    _stage(bank, folder, _file("notes.md", "My notes on alpha-project."))
    path, _ = _episode(bank, folder, "notes.md")
    minted = evidence.verify(bank, path.stem, "My notes on alpha-project")
    assert minted.kind == "user"
    fs.update(bank, folder["id"], authorship=[{"glob": "notes.md", "authorship": "agent"}])
    fs.reapply_authorship(bank, folder["id"])
    doc = provenance.episode_document(bank, path.stem, start=minted.start, end=minted.end, hash=minted.hash)
    assert {t.role for t in doc.turns} == {"assistant"}
    assert (doc.focus.kind, doc.focus.stale) == ("assistant", False)


# --- the route (R-B6's one commit, R-B7's papers) ------------------------------


def test_saving_new_rules_re_derives_in_one_user_commit(bank, client):
    folder = _folder(bank)
    assert client.post(f"/sources/folders/{folder['id']}/sync",
                       json=_body([_file("archive/sweep.md", "A sweep.")])).status_code == 200
    _git(bank, "add", "-A")
    _git(bank, "commit", "-q", "-m", "staged")
    path, _ = _episode(bank, folder, "archive/sweep.md")
    r = client.put(f"/sources/folders/{folder['id']}", json={"authorship": []})
    assert r.status_code == 200, r.text
    body = _git(bank, "log", "-1", "--format=%B")
    assert "Cicada-Author: user" in body and "trigger: folder/authorship" in body
    assert sorted(_git(bank, "show", "--name-only", "--format=", "HEAD").split()) == sorted(
        ["sources/folders.json", f"episodes/{path.name}"])
    assert _git(bank, "status", "--porcelain") == ""


def test_the_apps_re_post_after_saving_finds_nothing_to_do(bank, client):
    folder = _folder(bank)
    sweep = _file("archive/sweep.md", "A sweep.")
    client.post(f"/sources/folders/{folder['id']}/sync", json=_body([sweep]))
    client.put(f"/sources/folders/{folder['id']}", json={"authorship": []})
    again = client.post(f"/sources/folders/{folder['id']}/sync", json=_body([sweep])).json()
    assert (again["filesUnchanged"], again["updated"]) == (1, 0)


def test_a_papers_why_moves_with_the_file(bank, client):
    folder = _folder(bank)
    client.post(f"/sources/folders/{folder['id']}/sync", json=_body([_file("refs.md", REFS)]))
    client.put(f"/sources/folders/{folder['id']}", json={"authorship": [{"glob": "refs.md", "authorship": "agent"}]})
    saved = [c for c in parse_claims(markdown_parser.parse(bank / "entities" / f"{ALPHA}.md").body)
             if c.predicate == "saved-because"]
    closed = [c for c in saved if c.valid_to]
    (open_,) = [c for c in saved if not c.valid_to]
    assert [c.observer for c in closed] == ["owner"]
    assert (open_.observer, open_.source_trust, open_.evidence[0].kind) == ("agent", "agent_reflected", "assistant")


def test_while_sleep_runs_the_paper_step_waits(bank, client, monkeypatch):
    from api.services import sleep_cycle

    folder = _folder(bank)
    client.post(f"/sources/folders/{folder['id']}/sync", json=_body([_file("refs.md", REFS)]))
    before = (bank / "entities" / f"{ALPHA}.md").read_text(encoding="utf-8")
    monkeypatch.setattr(sleep_cycle, "get_sleep_state", lambda: SimpleNamespace(status="running"))
    client.put(f"/sources/folders/{folder['id']}", json={"authorship": [{"glob": "refs.md", "authorship": "agent"}]})
    assert _episode(bank, folder, "refs.md")[1].frontmatter["evidence_kind"] == "assistant"
    assert fs.get_folder(bank, folder["id"])["papers_pending"] is True
    assert (bank / "entities" / f"{ALPHA}.md").read_text(encoding="utf-8") == before
```

Run it → `AttributeError: module 'api.services.folder_source' has no attribute 'reapply_authorship'`.

- [ ] **Step 2: `episode_staging.reattribute`.** After `_requeue_for_authorship`:

```python
def reattribute(path: Path, *, extra: dict, queue_for_sleep: bool) -> bool:
    """Same body, same hash, new authorship (F2-back R-B6): a folder's rule
    changed, and the episode must say whose words it holds without the app
    re-posting a byte. Frontmatter only — ``content_hash``, ``content_sha``,
    ``source_id``, ``source_deleted_at`` and the body are untouched, so every
    evidence span into it stays ``current`` (G118) and a tombstone stays one.

    The queue follows :func:`_requeue_for_authorship`, the rule ``_refresh``
    and ``_repoint`` already share, so a rule change and a glob flip on re-post
    cannot disagree (R-B7) — for a tombstoned episode too, because an agent's
    words are never queued for Sleep (R-LS10) and a deletion never touched the
    queue. Returns whether the file changed. Runs under ``STAGE_LOCK``."""
    with STAGE_LOCK:
        parsed = markdown_parser.parse(path)
        fm = dict(parsed.frontmatter)
        before = dict(fm)
        fm.update(extra)
        _requeue_for_authorship(fm, EpisodeDraft(queue_for_sleep=queue_for_sleep))
        if fm == before:
            return False
        if "turns" in fm:
            fm["turns"] = fm.pop("turns")  # R-PB4: the sidecar stays the last key
        markdown_parser.write(path, fm, parsed.body)
        return True
```

- [ ] **Step 3: `folder_source.reapply_authorship`.** Append to the module docstring's
"Authorship (R-F2)" paragraph: "A changed rule re-derives every existing episode of the folder in
place (:func:`reapply_authorship`, F2-back R-B6), so the app never has to re-post a byte for it."
Below `CHANNEL_PREFIX` add `AUTHORSHIP_TRIGGER = "folder/authorship"`. After `live_file_count`:

```python
def reapply_authorship(memory_path: Path, folder_id: str) -> dict:
    """Re-derive whose words each existing episode of the folder holds, from the
    folder's CURRENT rules (F2-back R-B6). Before this, a changed rule reached
    only the files the app happened to re-post, and the owner's review found a
    folder's episodes still labelled by the old rule.

    Idempotent — an episode already matching its rule is not touched, so it runs
    on every save that carries rules. Returns ``{"paths": [bank-relative
    episodes written], "touched": {source_id: episode id — live ones, for the
    paper step}, "to_owner": n, "to_agent": n}``. Holds ``_LOCK`` then (inside
    ``reattribute``) ``STAGE_LOCK`` — the module's documented order."""
    memory_path = Path(memory_path)
    out: dict = {"paths": [], "touched": {}, "to_owner": 0, "to_agent": 0}
    with _LOCK:
        folder = get_folder(memory_path, folder_id)
        if folder is None:
            return out
        rules = folder.get("authorship") or []
        index, _ = episode_staging.scan(memory_path / "episodes")
        for rel, entries in sorted(_by_relpath(index, folder_id).items()):
            who = authorship_for(rel, rules)
            kind = "user" if who == "user" else "assistant"
            for sid, entry in entries:
                if entry.fm.get("authorship") == who and entry.fm.get("evidence_kind") == kind:
                    continue
                if not episode_staging.reattribute(entry.path, extra={"authorship": who, "evidence_kind": kind},
                                                   queue_for_sleep=who == "user"):
                    continue
                out["paths"].append(f"episodes/{entry.path.name}")
                out["to_owner" if who == "user" else "to_agent"] += 1
                # A deleted file's paper claims closed when it was tombstoned:
                # only a live episode goes to the paper step (R-B7).
                if not entry.fm.get("source_deleted_at"):
                    out["touched"][sid] = entry.id
    return out
```

- [ ] **Step 4: The routes.** In `routers/local_sources.py`, add above `register_folder`:

```python
async def _reapply_authorship(memory_path, folder: dict) -> list[str]:
    """F2-back R-B6/R-B7: re-derive every existing episode's authorship from the
    folder's current rules, then bring its papers' why-claims in line — through
    `papers.reconcile`, which reads the authorship each episode now declares.
    While Sleep runs the paper step waits (R-LS17). Returns the paths written."""
    moved = await run_in_threadpool(folder_source.reapply_authorship, memory_path, folder["id"])
    paths = list(moved["paths"])
    if not moved["touched"]:
        return paths
    from api.services import sleep_cycle

    if sleep_cycle.get_sleep_state().status == "running":
        folder_source.set_flags(memory_path, folder["id"], papers_pending=True)
        return paths + [f"sources/{folder_source.FOLDERS_FILENAME}"]
    current = folder_source.get_folder(memory_path, folder["id"]) or folder
    report = await run_in_threadpool(papers.reconcile, memory_path, current, touched=moved["touched"], tombstoned={})
    return paths + list(report["paths"])
```

In `register_folder`, replace the final commit (`:59-64`) with:

```python
    paths = [f"sources/{folder_source.FOLDERS_FILENAME}"]
    if project_id:
        paths.append(f"entities/{project_id}.md")
    trigger = "user/companion_app"
    if req.authorship is not None:
        # A re-pick that carries rules is a rules change too (R-B6); a new folder has nothing to move.
        moved = await _reapply_authorship(memory_path, folder)
        if moved:
            paths += moved
            trigger = folder_source.AUTHORSHIP_TRIGGER
    await folder_source.commit_paths_for(
        memory_path, paths, subject=f"Folder added ({folder['label']})", trigger=trigger,
        channel=folder_source.channel_id(folder["id"]))
    return _record(folder)
```

Replace `update_folder` with:

```python
@router.put("/sources/folders/{folder_id}", response_model=FolderRecord)
async def update_folder(folder_id: str, req: FolderUpdateRequest, settings: Settings = Depends(get_settings)):
    memory_path = settings.memory_path
    folder = folder_source.update(
        memory_path, folder_id, label=req.label,
        authorship=[r.model_dump() for r in req.authorship] if req.authorship is not None else None)
    if folder is None:
        raise HTTPException(404, f"No folder {folder_id!r}")
    paths = [f"sources/{folder_source.FOLDERS_FILENAME}"]
    trigger = "user/companion_app"
    if req.authorship is not None:
        # F2-back R-B6: the rules and the episodes they relabel land in ONE `user` commit.
        paths += await _reapply_authorship(memory_path, folder)
        trigger = folder_source.AUTHORSHIP_TRIGGER
    await folder_source.commit_paths_for(
        memory_path, paths, subject=f"Folder settings ({folder['label']})", trigger=trigger,
        channel=folder_source.channel_id(folder_id))
    return _record(folder)
```

- [ ] **Step 5: Green.** `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_folder_authorship_reapply.py api/tests/test_folder_source.py api/tests/test_papers.py api/tests/test_episode_staging.py api/tests/test_pending_commits.py -q -p no:cacheprovider` → 0 failures.

- [ ] **Step 6: Docs.** `CLAUDE.md`, the Awake rail "A local source is read by the app and parsed
by the backend" — after "…files under an agent glob land as `evidence_kind: assistant`, already
processed, so an agent's sweep is never the owner's words." insert:

```markdown
Saving new rules re-derives every existing episode of the folder in place — frontmatter only, the
hash unchanged; agent → owner is queued, owner → agent is parked unless Sleep already read it — in one
`user` commit (trigger `folder/authorship`), and the papers' why-claims follow (F2-back R-B6, R-B7).
```

TODO F2-back list, append:

```markdown
- Saving a folder's authorship rules re-derives its existing episodes in place — same bytes, same
  hash, agent → owner re-queued, owner → agent parked unless Sleep already read it — and its papers'
  why-claims follow; the app no longer has to re-post a byte (R-B6 … R-B8).
```

`memory-evolution.md` G133: insert before the row's closing ` | ✅ round 3 |`:

```markdown
 **F2-back:** a rules change re-derived only the files the app re-posted; saving rules now re-derives every existing episode in place (R-B6, R-B7). A belief Sleep formed from a file later declared an agent's keeps its minted span kind — the owner's call (R-B8).
```

- [ ] **Step 7: Full suite, then commit.**

```bash
cd <worktree> && git add api/services/episode_staging.py api/services/folder_source.py \
  api/routers/local_sources.py api/tests/test_folder_authorship_reapply.py CLAUDE.md \
  docs/goals/TODO.md docs/goals/memory-evolution.md
git commit -m "fix(folders): saving authorship rules re-derives existing episodes (R-B6…R-B8, G133)

A changed rule reached only files the app happened to re-post. PUT (and a re-pick
POST) with rules now re-derives every existing episode of the folder in place:
frontmatter only, hash unchanged, the stager's own queue rule, papers re-parsed,
one user commit with trigger folder/authorship.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Agent writes are labelled by their harness; the placeholder reads as `agent` (R-B9 · R-B10 · R-B11)

**Files:**
- Modify: `api/services/git_service.py` (constants beside `CICADA_AUTHOR:278`; `canonical_author`,
  `_harness_authors`; `_classify_author_kind:311-326`; `author_identity:356-362`;
  `from functools import lru_cache`)
- Modify: `api/services/agentic_write.py:93-103, :553, :557-577` (+ `git_service` in its import line)
- Modify: `api/services/telegram_capture.py:328-345`, `api/services/wispr_flow.py:434-437`,
  `api/services/papers.py:374`
- Modify: `api/services/transclusion_resolver.py:52`, `api/services/provenance.py:280, :444`,
  `api/services/inbox_service.py:188, :654`
- Modify: `api/routers/contributors.py:34`, `api/routers/claims.py:140-142`,
  `api/routers/episodes.py:34, :140` (the `AUTHOR_SHAPE` ETag tag, R-B10)
- Modify: `api/models/schemas.py:192-217` (the `Contributor.kind` comment) — comments only
  (`ProvenanceContributor`'s docstring says "as on `Contributor`" and stays true)
- Modify: `api/tests/test_wispr_flow.py:152-154` (one assertion)
- Test: `api/tests/test_agent_labels.py` (new)
- Docs: `CLAUDE.md` (the `Cicada-Author` bullet), `docs/goals/TODO.md`, `docs/goals/memory-evolution.md` (G118, G135)

**Interfaces:**
- Produces `git_service.AGENT_AUTHOR = "agent"`, `LEGACY_AGENT_AUTHOR = "mcp-agentic-write"`,
  `HARNESS_KIND = "harness"`, `AUTHOR_SHAPE = "harness-1"`, `canonical_author(author) -> str`.
  `author_identity` may now answer `("harness", None)`.
- Consumes `source_overview.HARNESS_LABELS`.

- [ ] **Step 1: Failing tests** — `api/tests/test_agent_labels.py`:

```python
"""F2-back R-B9 … R-B11 — an agent's write is labelled by its harness, and the
pre-G135 `mcp-agentic-write` placeholder reads as `agent` everywhere without
rewriting history."""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from api.remote import catalog
from api.services import (
    agentic_write, git_service, markdown_parser, provenance, source_overview, telegram_capture,
    transclusion_resolver,
)
from api.services.claims import Claim, parse_claims, write_claims


def _claim(**kw) -> Claim:
    base = dict(id="clm_x", text="alpha-project uses sqlite", subject="alpha-project", predicate="uses",
                object="sqlite", observer="agent", origin="mcp", valid_from="2026-09-01")
    base.update(kw)
    return Claim(**base)


def _bank(tmp_path: Path) -> Path:
    bank = tmp_path / "bank"
    (bank / "entities").mkdir(parents=True)
    return bank


# --- R-B9: the bucket --------------------------------------------------------


def test_every_harness_label_is_a_harness_not_a_model():
    labels = ({k for k in source_overview.HARNESS_LABELS if k != "unknown"}
              | {a.harness for a in catalog.APPS.values()} | {"agent"})
    for label in labels:
        assert git_service.author_identity(label) == ("harness", None), label


def test_models_the_person_and_maintenance_keep_their_buckets():
    assert git_service.author_identity("claude-sonnet-4-5") == ("model", "anthropic")
    assert git_service.author_identity("gpt-5.4-mini") == ("model", "openai")
    assert git_service.author_identity("user") == ("user", None)
    assert git_service.author_identity("cicada") == ("system", None)
    assert git_service.author_identity(None) == ("unknown", None)


def test_contributors_bucket_a_harness_commit_as_a_harness(tmp_path):
    bank = _bank(tmp_path)
    for args in (("init", "-q"), ("config", "user.email", "t@example.com"), ("config", "user.name", "t")):
        subprocess.run(["git", *args], cwd=bank, check=True)
    (bank / "entities" / "alpha-project.md").write_text("x\n", encoding="utf-8")
    message = git_service.build_commit_message("Agent write", ["entities/alpha-project.md: updated (trigger: mcp/claude-code)"],
                                               authors=["claude-code"])
    git_service.commit_paths_sync(bank, message, ["entities/alpha-project.md"])
    (row,) = asyncio.run(git_service.get_contributors(bank))
    assert (row.author, row.kind, row.provider) == ("claude-code", "harness", None)


# --- R-B10: the placeholder, read -------------------------------------------


def test_the_old_placeholder_reads_as_an_agent():
    assert git_service.canonical_author("mcp-agentic-write") == "agent"
    assert git_service.canonical_author("claude-code") == "claude-code"
    assert git_service.canonical_author("") == "unknown"
    assert git_service.author_identity("mcp-agentic-write") == ("harness", None)


def test_a_claim_on_the_wire_names_the_agent_not_the_placeholder():
    model = transclusion_resolver.claim_to_model(_claim(authored_by="mcp-agentic-write"))
    assert (model.authored_by, model.author_kind, model.author_provider) == ("agent", "harness", None)
    model = transclusion_resolver.claim_to_model(_claim(authored_by="claude-code"))
    assert (model.authored_by, model.author_kind) == ("claude-code", "harness")


def test_provenance_counts_the_placeholder_and_agent_as_one_writer(tmp_path):
    bank = _bank(tmp_path)
    page = bank / "entities" / "alpha-project.md"
    claims = [_claim(id="clm_1", authored_by="mcp-agentic-write"),
              _claim(id="clm_2", object="redis", text="alpha-project uses redis", authored_by="agent"),
              _claim(id="clm_3", object="duckdb", text="alpha-project uses duckdb", authored_by="claude-code")]
    markdown_parser.write(page, {"name": "Alpha Project", "type": "project"},
                          write_claims("## Summary\nAlpha.\n", claims))
    by = {c.author: c for c in provenance.entity_provenance(bank, page).contributors}
    assert set(by) == {"agent", "claude-code"}
    assert (by["agent"].claims, by["agent"].kind, by["agent"].provider) == (2, "harness", None)


def test_the_placeholder_file_is_never_rewritten(tmp_path):
    bank = _bank(tmp_path)
    page = bank / "entities" / "alpha-project.md"
    markdown_parser.write(page, {"name": "Alpha Project", "type": "project"},
                          write_claims("## Summary\nAlpha.\n", [_claim(authored_by="mcp-agentic-write")]))
    before = page.read_bytes()
    provenance.entity_provenance(bank, page)
    assert page.read_bytes() == before


# --- R-B10: who may withdraw what -------------------------------------------


def test_the_agent_bucket_owns_only_what_an_unidentified_mcp_agent_wrote():
    mcp = _claim(id="clm_a", authored_by="agent", origin="mcp")
    note_taker = _claim(id="clm_b", authored_by="agent", origin="wispr-flow")
    folder = _claim(id="clm_c", authored_by="agent", origin="folder")
    assert agentic_write.owns(mcp, author="agent", origin=None)
    assert not agentic_write.owns(note_taker, author="agent", origin=None)
    assert not agentic_write.owns(folder, author="agent", origin=None)
    assert not agentic_write.owns(mcp, author="claude-code", origin=None)
    legacy = _claim(id="clm_d", authored_by="mcp-agentic-write", origin="mcp")
    assert agentic_write.owns(legacy, author="codex", origin=None), "Q-R5's legacy rule is unchanged"


# --- R-B11: new writes -------------------------------------------------------


def test_a_write_that_names_no_author_is_an_agents(tmp_path):
    bank = _bank(tmp_path)
    agentic_write.write_claim(bank, "alpha-project", "uses", "sqlite", observer="agent", force_new_entity=True)
    page = bank / "entities" / "alpha-project.md"
    (claim,) = parse_claims(markdown_parser.parse(page).body)
    assert claim.authored_by == "agent"
    assert "mcp-agentic-write" not in page.read_text(encoding="utf-8")


def test_telegrams_reason_is_the_persons(tmp_path):
    bank = _bank(tmp_path)
    telegram_capture._write_saved_because_claim(bank, "media-example", "for the alpha launch", "")
    (claim,) = parse_claims(markdown_parser.parse(bank / "entities" / "media-example.md").body)
    assert (claim.authored_by, claim.origin) == ("user", "telegram")


# --- R-B10: the ETag moves with the body -------------------------------------


def test_the_contributors_etag_moves_when_the_author_shape_does(tmp_path, monkeypatch):
    """The same commits now serialise with new kinds; `/contributors` is a Store
    domain with an on-disk cache, so a git_head-only ETag would 304 the old rows
    until the next commit (the `graph.NODE_SHAPE` rule)."""
    from fastapi.testclient import TestClient

    from api import config, main

    bank = _bank(tmp_path)
    for args in (("init", "-q"), ("config", "user.email", "t@example.com"), ("config", "user.name", "t")):
        subprocess.run(["git", *args], cwd=bank, check=True)
    (bank / "entities" / "alpha-project.md").write_text("x\n", encoding="utf-8")
    git_service.commit_paths_sync(bank, "seed", ["entities/alpha-project.md"])
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    try:
        client = TestClient(main.app)
        etag = client.get("/contributors").headers["etag"]
        assert client.get("/contributors", headers={"If-None-Match": etag}).status_code == 304
        monkeypatch.setattr(git_service, "AUTHOR_SHAPE", "harness-test")
        assert client.get("/contributors", headers={"If-None-Match": etag}).status_code == 200
    finally:
        config.get_settings.cache_clear()
```

In `test_wispr_flow.py`, the to-do test's final assertion block (`:152-154`) gains one line:

```python
    assert claim.authored_by == "agent"  # F2-back R-B11: Wispr Flow's model wrote the list
```

The paper side of R-B11 is pinned in Task 5's test file (`test_an_agent_files_paper_claims_are_the_agents`).

Run → `test_every_harness_label…` fails (`('model', 'anthropic')` for `claude-code`). That is the red.

- [ ] **Step 2: `git_service` — the bucket and the canonical author.** Add
`from functools import lru_cache` to the imports. After `CICADA_AUTHOR = "cicada"` add:

```python
# G135: a write that arrived through MCP is authored by its harness label, and
# `agent` when the harness never said which it was (`agent_commits.author_for`).
AGENT_AUTHOR = "agent"
# The placeholder every stdio MCP claim carried before G135 R-R11 — the
# reconcile shim's "model" name. History is never rewritten (F2-back R-B10):
# every reader shows it as `agent` through `canonical_author`.
LEGACY_AGENT_AUTHOR = "mcp-agentic-write"
# R-B9: the bucket the app already names (`OriginIconography.label`) and marks
# (`OriginMark`) — a harness label is neither a model nor a person.
HARNESS_KIND = "harness"
# R-B10: folded into the ETag `extra` of every read whose body carries an
# author kind (`/contributors`, `/entities/{id}/provenance`,
# `/episodes/{id}/citations`). Those bodies changed for the same commits and
# claims, so an ETag over the inputs alone would 304 the old kinds — the
# `graph.NODE_SHAPE` rule. Bump it the next time the author buckets move.
AUTHOR_SHAPE = "harness-1"


def canonical_author(author: str | None) -> str:
    """The author a reader shows (R-B10): the pre-G135 placeholder is `agent`,
    an empty author is the legacy `unknown` bucket, anything else is itself."""
    name = (author or "").strip() or UNKNOWN_AUTHOR
    return AGENT_AUTHOR if name == LEGACY_AGENT_AUTHOR else name


@lru_cache(maxsize=1)
def _harness_authors() -> frozenset[str]:
    """Every label a harness writes as `Cicada-Author` (R-B9): the Sources page's
    one harness table — stdio harnesses and every remote app (G135 R-R26) —
    minus its `unknown` bucket, plus `agent`. One table, so a new remote app is a
    harness here the day it is a card there. Imported lazily: `source_overview`
    reaches `folder_source`, and this module must stay importable on its own."""
    from api.services.source_overview import HARNESS_LABELS

    return frozenset(k for k in HARNESS_LABELS if k != UNKNOWN_AUTHOR) | {AGENT_AUTHOR}
```

`_classify_author_kind` becomes (docstring extended, one branch added before `return "model"`):

```python
def _classify_author_kind(author: str) -> str:
    """Bucket an author into "user" | "system" | "harness" | "model" | "unknown".

    "system" is the literal ``cicada`` (R-L6): maintenance with no model and no
    user in the loop. It used to fall through to "model", where
    ``_provider_for_model`` answered "other" and the app drew a grey "?" — so
    the state snapshot, the split-out decay commit and the migrations all
    rendered as an anonymous unknown model in Cicada's own contributors list.

    "harness" (F2-back R-B9) is an agent write's label — `claude-code`,
    `claude-web`, `agent` — and the pre-G135 placeholder. They answered "model",
    so `claude-code` wore Anthropic's mark by substring and the placeholder
    showed as a raw contributor name.
    """
    if author == USER_AUTHOR:
        return "user"
    if author == CICADA_AUTHOR:
        return "system"
    if author == UNKNOWN_AUTHOR:
        return "unknown"
    if author == LEGACY_AGENT_AUTHOR or author in _harness_authors():
        return HARNESS_KIND
    return "model"
```

`author_identity`'s body becomes:

```python
    name = canonical_author(author)
    return _classify_author_kind(name), _provider_for_model(name)
```

- [ ] **Step 3: Writers (R-B11).** `agentic_write.py`: add `git_service` to
`from api.services import decay_policy, entity_body, markdown_parser, telemetry`. The shim:

```python
@dataclass
class _ReconcileSettings:
    """Minimal settings shim satisfying claim_reconciler.reconcile_stage3's
    duck-typed ``settings`` argument (memory_path / litellm_model / thresholds).

    ``litellm_model`` is what ``_stamp_new`` stamps on a claim that arrives with
    no ``authored_by``: ``agent`` (F2-back R-B11), the G135 word for an agent
    that never said which it was — never a model name, since no model ran here.
    """

    memory_path: Path
    litellm_model: str = git_service.AGENT_AUTHOR
    archive_threshold: float = 0.2
    decay_nudge_threshold: float = 0.4
```

`:553` becomes `_LEGACY_MCP_AUTHOR = git_service.LEGACY_AGENT_AUTHOR`. It can no longer read the
shim's field, which is now `agent`. In the comment above it, change "`_stamp_new` stamps the same
placeholder on every claim that arrives without `authored_by`" to "`_stamp_new` stamped the same
placeholder on every claim that arrived without `authored_by` until F2-back R-B11". The rest of the
comment stays. `owns`' final `return` becomes:

```python
    authored_by = claim.authored_by or ""
    if authored_by == _LEGACY_MCP_AUTHOR:
        return claim_origin == _LEGACY_MCP_ORIGIN
    if authored_by == git_service.AGENT_AUTHOR:
        # F2-back R-B10: `agent` is also the author of a deterministic writer's
        # assistant words (a folder's agent glob, a note-taker's to-dos), so the
        # unidentified-agent bucket owns only what an unidentified MCP agent wrote.
        return author == git_service.AGENT_AUTHOR and claim_origin == _LEGACY_MCP_ORIGIN
    return authored_by == author
```

`telegram_capture._write_saved_because_claim`: add `from api.services import git_service` to its
local imports and `authored_by=git_service.USER_AUTHOR,` after `origin="telegram",`, with the comment
`# F2-back R-B11: the person typed the reason; its commit is already `user`.`

`wispr_flow.write_todo_claims`: add `from api.services import git_service` to its local import line,
and pass `authored_by=git_service.AGENT_AUTHOR` in the `write_claim` call, with the comment
`# F2-back R-B11: Wispr Flow's model wrote the list (its spans are `assistant`).`

`papers.py:374` holds two keywords on one line:
`            authored_by="user" if who == "user" else None, origin=ORIGIN,`. Replace the whole line
with these two lines, so the trailing comment cannot swallow `origin=ORIGIN`:

```python
            authored_by=who,  # F2-back R-B11: `user` or `agent`, from the file's authorship
            origin=ORIGIN,
```

- [ ] **Step 4: Readers (R-B10).** `transclusion_resolver.claim_to_model:52`:
`author = claim.authored_by or "unknown"` → `author = git_service.canonical_author(claim.authored_by)`.
`provenance.py:280`: `Counter((c.authored_by or git_service.UNKNOWN_AUTHOR) for c in current)` →
`Counter(git_service.canonical_author(c.authored_by) for c in current)`. `provenance.py:444`:
`"authored_by": claim.authored_by or git_service.UNKNOWN_AUTHOR,` →
`"authored_by": git_service.canonical_author(claim.authored_by),`. `inbox_service.py:188` (in
`_extractor_refs`) and `:654` (in `_feedback_refs`): `out["extractor_model"] = _opt_str(claim.authored_by)` →

```python
                    out["extractor_model"] = _opt_str(
                        git_service.canonical_author(claim.authored_by) if claim.authored_by else None)
```

with `from api.services import git_service` added as a local import at the top of EACH of those
two functions (keep the indentation of the line being replaced). The module imports `git_service`
only inside functions today; keep that pattern.

The ETag tag (R-B10), one `extra` each:

- `routers/contributors.py:34`: `etag = sync_service.etag_for(settings.memory_path, "git_head")` →
  `etag = sync_service.etag_for(settings.memory_path, "git_head", extra=git_service.AUTHOR_SHAPE)`
  (`git_service` is already imported there).
- `routers/claims.py:140-142` (`get_entity_provenance`): `extra=f"provenance|{page.stem}"` →
  `extra=f"provenance|{page.stem}|{git_service.AUTHOR_SHAPE}"` (already imported).
- `routers/episodes.py:140` (`get_episode_citations`): `extra=f"citations|{episode_id}"` →
  `extra=f"citations|{episode_id}|{git_service.AUTHOR_SHAPE}"`, and `:34`'s import line becomes
  `from api.services import evidence, git_service, provenance, sync_service`.

`/episodes/{id}/text` carries no author and keeps its recipe.

`schemas.py`: the `Contributor` comment block gains "`harness` for an agent write's label
(`claude-code`, `agent`, …; F2-back R-B9)" in the `kind` list, and `kind: str = "unknown"`'s trailing
comment becomes `# "user" | "system" | "harness" | "model" | "unknown"`. `ProvenanceContributor`'s
docstring: "``kind``/``provider`` as on ``Contributor``" stays true — no edit needed.

- [ ] **Step 5: Green.** `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_agent_labels.py api/tests/test_contributors.py api/tests/test_contributor_commits.py api/tests/test_entity_provenance.py api/tests/test_retract_claim.py api/tests/test_wispr_flow.py api/tests/test_telegram_capture.py api/tests/test_feedback_ledger.py api/tests/test_consumption_feedback.py api/tests/test_inbox_resolution_provenance.py api/tests/test_session_provenance_views.py api/tests/test_episode_citations.py api/tests/test_contributor_calendar.py api/tests/test_sync.py -q -p no:cacheprovider` → 0 failures.

- [ ] **Step 6: Docs.** `CLAUDE.md`, the `Cicada-Author:` bullet — after "…parsed by `_parse_authors`."
insert:

```markdown
`git_service.author_identity` buckets a harness label (and `agent`) as kind `harness`, which the app
names and marks as that app; the pre-G135 `mcp-agentic-write` claim placeholder reads as `agent`
through `canonical_author`, never rewritten (F2-back R-B9, R-B10). A read whose body carries an
author kind folds `git_service.AUTHOR_SHAPE` into its ETag; bump it when the buckets move.
```

TODO F2-back list, append:

```markdown
- Agent writes are labelled by their harness: `author_identity` has a `harness` kind, a write that
  names no author is `agent`, deterministic writers name whose words they hold, and the pre-G135
  placeholder reads as `agent` everywhere without rewriting history (R-B9 … R-B11). `/contributors`,
  `/entities/{id}/provenance` and `/episodes/{id}/citations` fold `git_service.AUTHOR_SHAPE` into
  their ETags, so no cache keeps the old kinds (R-B10).
```

`memory-evolution.md` G118: replace `a remote write's app label bucketed as `harness` by
`author_identity` (it reads as a model today), ` with `a remote write's app label bucketed as
`harness` by `author_identity` (done, F2-back R-B9), `. G135: replace
`A dedicated `harness` contributor kind (R-R26). ` with `A dedicated `harness` contributor kind
(R-R26) — done in F2-back (R-B9). `.

- [ ] **Step 7: Full suite, then commit.**

```bash
cd <worktree> && git add api/services/git_service.py api/services/agentic_write.py \
  api/services/telegram_capture.py api/services/wispr_flow.py api/services/papers.py \
  api/services/transclusion_resolver.py api/services/provenance.py api/services/inbox_service.py \
  api/routers/contributors.py api/routers/claims.py api/routers/episodes.py \
  api/models/schemas.py api/tests/test_agent_labels.py api/tests/test_wispr_flow.py CLAUDE.md \
  docs/goals/TODO.md docs/goals/memory-evolution.md
git commit -m "fix(provenance): harness labels are the harness kind; the placeholder reads as agent (R-B9…R-B11, G135)

author_identity called claude-code an Anthropic model and showed the pre-G135
mcp-agentic-write placeholder as a contributor. Harness labels (the Sources
harness table + agent) are now the harness kind the app already renders; every
reader maps the placeholder to agent without rewriting history; new writes
record who wrote the words (agent / user / the file's authorship). The three
reads whose bodies carry an author kind fold an author-shape tag into their
ETag, so no cache 304s the old kinds.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Paper why-claims drop in-document anchors, and existing ones are repaired once (R-B12 · R-B13)

**Files:**
- Modify: `api/services/papers.py` (new cleaner block after `_TRAILING:87`; `desired_claims`' inner
  `claim:360-380`; `apply_claims:431-446`)
- Create: `api/services/paper_claim_text_migration.py`
- Modify: `api/services/bank_migrations.py` (import; call after the placeholder rewrite; return key)
- Test: `api/tests/test_paper_claim_text.py` (new)
- Docs: `docs/goals/TODO.md`

**Interfaces:**
- Produces `papers.clean_claim_text(text) -> str`, `papers.repair_claim_text(claim) -> bool`,
  `paper_claim_text_migration.repair_paper_claim_text(memory_path) -> {"pages", "claims"}`,
  `run_bank_migrations(...)["paper_claim_text"]`.
- Consumes Task 1's `git_service.commit_paths_sync`, `folder_source._LOCK`.

- [ ] **Step 1: Failing tests** — `api/tests/test_paper_claim_text.py`:

```python
"""F2-back R-B12, R-B13 — paper why-claims never carry in-document anchors or
footnote markers; the episode keeps them, ids never move, and existing banks
are repaired once."""
from __future__ import annotations

import base64
import hashlib
import subprocess
from pathlib import Path

import pytest

from api.services import bank_index, bank_migrations, folder_source as fs, markdown_parser, papers
from api.services import paper_claim_text_migration as mig
from api.services.claims import parse_claims, write_claims

NOISY = "the architecture alpha-project builds on [N50](#note-n50)."
CLEAN = "the architecture alpha-project builds on."
REFS = f"# References\n\n## Retrieval\n\n- [Paper Alpha](https://arxiv.org/abs/2401.00001) — {NOISY}\n"
ALPHA = "media-arxiv-2401-00001"


@pytest.mark.parametrize("raw, want", [
    ("Great baseline for retrieval [N50](#note-n50).", "Great baseline for retrieval."),
    ("Great baseline for retrieval ([N50](#note-n50)).", "Great baseline for retrieval."),
    ("Compare with [the method section](#method) here", "Compare with the method section here"),
    ("Strong results[^3] on long context", "Strong results on long context"),
    ("Anchors [N1](#n1), [N2](#n2), and more", "Anchors, and more"),
    ("Why it matters [N50](#note-n50), [N51](#note-n51)", "Why it matters"),
    ("Retrieval [↩](#top)", "Retrieval"),
    ("Cited twice [^a][^b].", "Cited twice."),
    ("[N50](#note-n50)", ""),
    # Untouched: no in-document link and no footnote marker.
    ("Uses [a public link](https://example.com/a) too", "Uses [a public link](https://example.com/a) too"),
    ("Two  spaces stay when nothing was stripped", "Two  spaces stay when nothing was stripped"),
])
def test_clean_claim_text(raw, want):
    assert papers.clean_claim_text(raw) == want


def _file(rel, text, mtime=1_756_000_000.0):
    raw = text.encode("utf-8")
    return fs.IncomingFile(rel, mtime, hashlib.sha256(raw).hexdigest(), base64.b64encode(raw).decode())


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True).stdout


def _bank(tmp_path: Path, *, git: bool = False) -> tuple[Path, dict]:
    bank = tmp_path / "bank"
    for sub in ("episodes", "entities", "sources"):
        (bank / sub).mkdir(parents=True)
    if git:
        _git(bank, "init", "-q")
        _git(bank, "config", "user.email", "test@example.com")
        _git(bank, "config", "user.name", "Cicada Test")
    project_id, _ = fs.ensure_project(bank, "alpha-project", path="/Users/example/alpha-project", device="mac-1")
    folder = fs.register(bank, label="alpha-project", path="/Users/example/alpha-project", device="mac-1",
                         project_id=project_id)
    return bank, folder


def _sync(bank, folder, files):
    bank_index.invalidate()
    staged = fs.sync(bank, folder, files, [])["_staged"]
    return papers.reconcile(bank, fs.get_folder(bank, folder["id"]), touched=staged.touched,
                            tombstoned=staged.tombstoned_sources, renamed=staged.renamed_sources)


def _saved(bank):
    return [c for c in parse_claims(markdown_parser.parse(bank / "entities" / f"{ALPHA}.md").body)
            if c.predicate == "saved-because"]


# --- R-B12: the writer -------------------------------------------------------


def test_a_noisy_note_is_written_clean_and_its_span_still_points_at_the_raw_words(tmp_path):
    bank, folder = _bank(tmp_path)
    _sync(bank, folder, [_file("REFERENCES.md", REFS)])
    (claim,) = _saved(bank)
    assert (claim.text, claim.object) == (CLEAN, CLEAN)
    body = markdown_parser.parse(next((bank / "episodes").glob("ep_*.md"))).body
    assert "[N50](#note-n50)" in body, "the episode keeps its anchors (G118: spans, not copies)"
    (ev,) = claim.evidence
    assert body[ev.start:ev.end] == NOISY
    assert claim.id == papers.claim_id(ALPHA, "saved-because", NOISY, "owner", f"folder:{folder['id']}:retrieval")


def test_a_note_of_only_anchors_writes_no_reason(tmp_path):
    bank, folder = _bank(tmp_path)
    only = "## Retrieval\n\n- [Paper Alpha](https://arxiv.org/abs/2401.00001) — [N50](#note-n50)\n"
    _sync(bank, folder, [_file("REFERENCES.md", only)])
    assert _saved(bank) == []


def test_an_agent_files_paper_claims_are_the_agents(tmp_path):
    """R-B11's paper half: `authored_by` was None — "Before provenance" in the app."""
    bank, folder = _bank(tmp_path)
    _sync(bank, folder, [_file("archive/sweep.md", "See arXiv:2401.00009 for more.")])
    (cited,) = [c for c in parse_claims(markdown_parser.parse(bank / "entities" / "media-arxiv-2401-00009.md").body)
                if c.predicate == "cited-in"]
    assert cited.authored_by == "agent"


def _make_noisy(bank):
    """The pre-fix shape: the anchor inside the stored text and object."""
    page = bank / "entities" / f"{ALPHA}.md"
    parsed = markdown_parser.parse(page)
    claims = parse_claims(parsed.body, strict=True)
    for c in claims:
        if c.predicate == "saved-because":
            c.text = c.object = NOISY
    markdown_parser.write(page, parsed.frontmatter, write_claims(parsed.body, claims))


def test_a_sync_repairs_noisy_words_on_a_claim_it_re_reads(tmp_path):
    bank, folder = _bank(tmp_path)
    _sync(bank, folder, [_file("REFERENCES.md", REFS)])
    ids = {c.id for c in _saved(bank)}
    _make_noisy(bank)
    _sync(bank, folder, [_file("REFERENCES.md", "Intro.\n\n" + REFS, mtime=1_756_100_000.0)])
    (claim,) = _saved(bank)
    assert (claim.text, claim.object, claim.valid_to) == (CLEAN, CLEAN, None)
    assert {claim.id} == ids


# --- R-B13: the one-shot repair ----------------------------------------------


def _seeded(tmp_path):
    bank, folder = _bank(tmp_path, git=True)
    _sync(bank, folder, [_file("REFERENCES.md", REFS)])
    _make_noisy(bank)
    _git(bank, "add", "-A")
    _git(bank, "commit", "-q", "-m", "seed")
    bank_index.invalidate()
    return bank, folder


def test_the_repair_cleans_the_words_and_keeps_every_id(tmp_path):
    bank, _ = _seeded(tmp_path)
    ids = {c.id for c in _saved(bank)}
    assert mig.repair_paper_claim_text(bank) == {"pages": 1, "claims": 1}
    (claim,) = _saved(bank)
    assert (claim.text, claim.object) == (CLEAN, CLEAN) and {claim.id} == ids


def test_the_commit_is_cicada_authored_and_holds_exactly_the_rewritten_page(tmp_path):
    bank, _ = _seeded(tmp_path)
    mig.repair_paper_claim_text(bank)
    body = _git(bank, "log", "-1", "--format=%B")
    assert "Cicada-Author: cicada" in body and "trigger: maintenance/paper_claim_text" in body
    assert _git(bank, "show", "--name-only", "--format=", "HEAD").split() == [f"entities/{ALPHA}.md"]


def test_it_runs_once_and_a_second_pass_changes_nothing(tmp_path):
    bank, _ = _seeded(tmp_path)
    mig.repair_paper_claim_text(bank)
    head = _git(bank, "rev-parse", "HEAD")
    assert mig.repair_paper_claim_text(bank) == {"pages": 0, "claims": 0}
    (bank / ".paper_claim_text_v1").unlink()
    assert mig.repair_paper_claim_text(bank) == {"pages": 0, "claims": 0}
    assert _git(bank, "rev-parse", "HEAD") == head


def test_a_full_reparse_after_the_repair_changes_no_claim(tmp_path):
    bank, folder = _seeded(tmp_path)
    mig.repair_paper_claim_text(bank)
    bank_index.invalidate()
    assert papers.reparse_folder(bank, fs.get_folder(bank, folder["id"]))["claims_changed"] == 0


def test_a_page_that_cannot_be_written_keeps_the_marker_off(tmp_path, monkeypatch):
    bank, _ = _seeded(tmp_path)
    real = markdown_parser.write

    def flaky(path, frontmatter, body):
        if Path(path).stem == ALPHA:
            raise OSError("disk full")
        return real(path, frontmatter, body)

    monkeypatch.setattr(markdown_parser, "write", flaky)
    assert mig.repair_paper_claim_text(bank) == {"pages": 0, "claims": 0}
    assert not (bank / ".paper_claim_text_v1").exists(), "the next start retries"


def test_a_corrupt_claims_block_is_skipped_and_never_raises(tmp_path):
    bank, _ = _seeded(tmp_path)
    page = bank / "entities" / f"{ALPHA}.md"
    parsed = markdown_parser.parse(page)
    fence = "`" * 3
    markdown_parser.write(page, parsed.frontmatter,
                          parsed.body.split(fence + "claims")[0] + f"{fence}claims\n- id: [unclosed\n{fence}\n")
    before = page.read_bytes()
    assert mig.repair_paper_claim_text(bank) == {"pages": 0, "claims": 0}
    assert page.read_bytes() == before


def test_bank_migrations_runs_the_repair(tmp_path):
    bank, _ = _seeded(tmp_path)
    assert bank_migrations.run_bank_migrations(bank)["paper_claim_text"] == {"pages": 1, "claims": 1}
```

Run → collection fails with `ModuleNotFoundError: No module named
'api.services.paper_claim_text_migration'` (the module-level import). With that module stubbed, the
parametrized cases fail with `AttributeError: module 'api.services.papers' has no attribute
'clean_claim_text'`. That is the red.

- [ ] **Step 2: The cleaner (R-B12).** In `papers.py`, after `_TRAILING = …`:

```python
# F2-back R-B12: a folder's markdown cross-references its own notes —
# `builds on [N50](#note-n50).` — and the note became a claim's words verbatim,
# so the anchor showed on the card. These strip what only means something INSIDE
# the file; the episode keeps it (G118: spans point into the stored text).
_ANCHOR_LINK_RE = re.compile(r"\[([^\]\n]*)\]\(#[^)\s]*\)")
_FOOTNOTE_RE = re.compile(r"\[\^[^\]\s]+\]")
_REF_LABEL_RE = re.compile(r"^\^?[A-Za-z]{0,4}[-_.]?\d{1,4}[a-z]?$")
_SPACE_RUN_RE = re.compile(r"[ \t]{2,}")
_SPACE_BEFORE_PUNCT_RE = re.compile(r"[ \t]+([,.;:!?)\]])")
_EMPTY_BRACKETS_RE = re.compile(r"\(\s*\)|\[\s*\]")
_REPEATED_SEPARATOR_RE = re.compile(r"([,;])(?:[ \t]*[,;])+")


def _anchor_label(m: re.Match) -> str:
    label = m.group(1).strip()
    if not label or _REF_LABEL_RE.match(label) or not any(ch.isalnum() for ch in label):
        return ""  # a reference label (`N50`, `12`, `fn3`) or a glyph (`↩`) says nothing
    return label  # prose that happened to be a link keeps its words


def clean_claim_text(text: str) -> str:
    """A paper claim's words without in-document anchors or footnote markers
    (R-B12). Text with neither is returned byte-identical; an external link is
    never touched."""
    raw = text or ""
    if not (_ANCHOR_LINK_RE.search(raw) or _FOOTNOTE_RE.search(raw)):
        return raw
    out = _ANCHOR_LINK_RE.sub(_anchor_label, raw)
    out = _FOOTNOTE_RE.sub("", out)
    out = _EMPTY_BRACKETS_RE.sub("", out)
    out = _SPACE_RUN_RE.sub(" ", out)
    out = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", out)
    out = _REPEATED_SEPARATOR_RE.sub(r"\1", out)
    return out.strip().rstrip(",;").strip()


def repair_claim_text(claim: Claim) -> bool:
    """Clean a paper claim's ``text`` and, when literal, its ``object`` (R-B13).
    The id is left alone — it was minted from the raw words (R-FX5) and the
    writer mints it from them again. Words that clean to nothing are kept: the
    writer's next re-parse closes that claim. Returns whether anything changed."""
    changed = False
    text = clean_claim_text(claim.text)
    if text and text != claim.text:
        claim.text, changed = text, True
    if claim.object_kind == "literal":
        obj = clean_claim_text(claim.object)
        if obj and obj != claim.object:
            claim.object, changed = obj, True
    return changed
```

`desired_claims`' inner `claim` — after `if cid in out: return` insert, and use the results in the
`Claim(...)`:

```python
        # R-B12: the id above is minted from the RAW words (R-FX5, so every
        # existing id is minted again); what the claim says is the clean words,
        # and its evidence still quotes the raw ones the episode holds.
        shown = clean_claim_text(obj) if literal else obj
        words = clean_claim_text(text_)
        if not shown or not words:
            return  # a note that was nothing but anchors says nothing about why
        made = Claim(
            id=cid, text=words, subject=entity_id, predicate=predicate, object=shown,
            object_kind="literal" if literal else "node", observer=observer, context=PAPER_CONTEXT,
            epistemic="explicit", source_trust=trust, confidence=_CONFIDENCE[who][predicate],
            valid_from=valid_from, recorded_at=today, source_episodes=[episode_id],
            authored_by=who,  # F2-back R-B11: `user` or `agent`, from the file's authorship
            origin=ORIGIN,
            evidence=[evidence.verify(None, episode_id, quote, text=text, window=window, kind_override=kind)],
        )
```

`apply_claims`, after `old.context = new.context` (`:446`):

```python
        # R-B13: a sync repairs anchor noise on any claim it re-reads, as it repairs a pre-F1 context.
        repair_claim_text(old)
```

`_same_slot`'s docstring gains one closing sentence (R-B12's disclosed consequence): "A note whose
raw words had anchors is stored clean, so its stored object no longer reproduces its id and this
answers False: an edit closes it with no ``superseded_by`` — never a wrong one (F2-back R-B12)."

- [ ] **Step 3: The migration (R-B13).** `api/services/paper_claim_text_migration.py`:

```python
"""F2-back (R-B12, R-B13) — one-shot, idempotent: strip in-document anchor links
and footnote markers from the words of folder-paper claims written before the
writer learned to (`papers.clean_claim_text`).

A folder's markdown cross-references its own notes — `builds on [N50](#note-n50).`
— and `desired_claims` stored the note verbatim as a `saved-because` claim's text
and object, so the anchor showed on the paper's card. The writer now cleans at
write and a sync repairs what it re-reads, but a file nobody edits is never
re-read, so existing pages are repaired here once.

Scope, exactly: claims with ``origin == folder`` and a why-predicate on
``media.kind: paper`` pages. Only ``text`` and a literal ``object`` change; ids do
not (they were minted from the raw words, R-FX5); the episode is never touched,
so no evidence span moves (G118). The `paper_context_migration` shape (F1
R-FX6): marker-guarded, held under ``folder_source._LOCK`` through the commit, one
commit scoped to exactly the rewritten pages as ``Cicada-Author: cicada`` through
the bank's one write lock (R-B1). One page that cannot be read or written never
stops the rest, what did land is still committed, and any failure keeps the
marker off so the next start retries. Never raises.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from loguru import logger

from api.services import bank_index, folder_source, git_service, markdown_parser, papers
from api.services.claims import MalformedClaimsBlockError, parse_claims, write_claims

_MARKER = ".paper_claim_text_v1"
TRIGGER = "maintenance/paper_claim_text"
_NOTHING = {"pages": 0, "claims": 0}


def repair_paper_claim_text(memory_path) -> dict:
    """Repair one bank. Returns ``{"pages": n, "claims": n}``."""
    memory_path = Path(memory_path)
    if not (memory_path / "entities").exists() or (memory_path / _MARKER).exists():
        return dict(_NOTHING)
    try:
        with folder_source._LOCK:
            written, repaired, failed = _rewrite(memory_path)
            report = {"pages": len(written), "claims": repaired}
            rel = [f"entities/{p.name}" for p in written]
            if rel:
                try:
                    _commit(memory_path, rel)
                except Exception as e:
                    # Right on disk, uncommitted (or no git here): no marker, so the
                    # next start re-scans, finds nothing left and writes it.
                    logger.warning(f"Paper claim-text repair commit skipped: {e}")
                    return report
    except Exception as e:
        logger.error(f"Paper claim-text repair FAILED — will retry on next start: {e}")
        return dict(_NOTHING)
    if not failed:
        (memory_path / _MARKER).write_text("v1", encoding="utf-8")
    return report


def _rewrite(memory_path: Path) -> tuple[list[Path], int, bool]:
    """``(pages written, claims repaired, whether any page failed)``."""
    written: list[Path] = []
    repaired = 0
    failed = False
    bank_index.invalidate(memory_path)
    for f in bank_index.files(memory_path, "entities"):
        if not papers.is_paper(f.frontmatter or {}):
            continue
        try:
            parsed = markdown_parser.parse(f.path)
            claims = parse_claims(parsed.body, strict=True)
        except MalformedClaimsBlockError as exc:
            logger.error(f"corrupt claims block on {f.path.name}, paper claim text skipped: {exc}")
            continue
        except Exception as exc:
            logger.error(f"could not read {f.path.name}, paper claim text retried next start: {exc}")
            failed = True
            continue
        here = sum(1 for c in claims
                   if c.origin == papers.ORIGIN and c.predicate in papers.WHY_PREDICATES and papers.repair_claim_text(c))
        if not here:
            continue
        try:
            markdown_parser.write(f.path, parsed.frontmatter, write_claims(parsed.body, claims))
        except Exception as exc:
            logger.error(f"could not rewrite {f.path.name}, paper claim text retried next start: {exc}")
            failed = True
            continue
        written.append(f.path)
        repaired += here
    return written, repaired, failed


def _commit(memory_path: Path, rel: list[str]) -> None:
    message = git_service.build_commit_message(
        f"Repair paper claim text {date.today().isoformat()}",
        [f"{p}: updated (trigger: {TRIGGER})" for p in rel],
        authors=[git_service.CICADA_AUTHOR],
    )
    git_service.commit_paths_sync(memory_path, message, rel)
```

`bank_migrations.py`: import `from api.services.paper_claim_text_migration import
repair_paper_claim_text`; after the placeholder block add

```python
    # F2-back (R-B13): one-time strip of in-document anchors (`[N50](#note-n50)`)
    # and footnote markers from folder-paper claims' words — ids unchanged.
    paper_claim_text = repair_paper_claim_text(memory_path)
    if paper_claim_text["claims"]:
        logger.info(
            f"Repaired the words of {paper_claim_text['claims']} paper claim(s) on "
            f"{paper_claim_text['pages']} page(s)"
        )
```

add `"paper_claim_text": paper_claim_text,` to the returned dict, and extend the docstring's shape
with `"paper_claim_text": {"pages": int, "claims": int}`.

- [ ] **Step 4: Green.** `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_paper_claim_text.py api/tests/test_papers.py api/tests/test_paper_context_migration.py api/tests/test_placeholder_summary_migration.py api/tests/test_folder_authorship_reapply.py -q -p no:cacheprovider` → 0 failures.

- [ ] **Step 5: Docs.** TODO F2-back list, append:

```markdown
- Paper why-claims no longer carry in-document anchors (`[N50](#note-n50)`) or footnote markers;
  the episode keeps them, ids are unchanged, a sync repairs what it re-reads, and existing banks are
  repaired once as `cicada` (R-B12, R-B13).
```

- [ ] **Step 6: Full suite, then commit.**

```bash
cd <worktree> && git add api/services/papers.py api/services/paper_claim_text_migration.py \
  api/services/bank_migrations.py api/tests/test_paper_claim_text.py docs/goals/TODO.md
git commit -m "fix(papers): why-claims drop in-document anchors; existing ones repaired once (R-B12, R-B13, G133)

A folder note like 'builds on [N50](#note-n50).' became a claim's words verbatim.
The writer now strips in-document links and footnote markers from a paper claim's
text and literal object, keeps the raw words as the evidence quote and the id
source (R-FX5), and a marker-guarded cicada-authored repair fixes existing banks.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: The video and meeting skill bridges go active; documents stays off (R-B14)

**Files:**
- Modify: `api/data/recommended_skills.json:36, :70, :84, :158`
- Modify: `api/services/skill_catalog.py:20-23` (docstring), `:49-52` (`BRIDGE_TEXT`)
- Modify: `api/tests/test_skill_catalog.py:62, :164-175` (+ new tests)
- Modify: `api/tests/test_handshake_bridges.py` (one new test)
- Docs: `CLAUDE.md` (Settings → Skills), `docs/goals/TODO.md`, `docs/goals/memory-evolution.md` (G138)

**Interfaces:**
- Produces `BRIDGE_TEXT["video"]`, `BRIDGE_TEXT["meetings"]`.
- Consumes `cicada_record_watch(url, summary, excerpts)` and `cicada_save_episode(content, title)`
  schemas (R12), `evidence.speaker_kind`.

- [ ] **Step 1: Failing tests.** In `test_skill_catalog.py`, `:62` becomes
`assert watch["bridge"] == {"key": "video", "tool": "cicada_record_watch", "active": True}`. Replace
the bridge test at `:164-175` with:

```python
def test_bridge_lines_only_for_installed_active_bridges_in_that_agent(tmp_path):
    home = tmp_path / "h"
    assert skill_catalog.bridge_lines("claude-code", home=home) == []
    _skill(home, ".claude/skills", "paper-lookup")
    plugins = home / ".claude" / "plugins"
    plugins.mkdir(parents=True)
    # `pdf` is installed, but its `documents` bridge stays inactive (R-B14).
    (plugins / "installed_plugins.json").write_text(json.dumps({"document-skills@anthropic-agent-skills": {}}))
    lines = skill_catalog.bridge_lines("claude-code", home=home)
    assert len(lines) == 1 and "`paper-lookup` is installed" in lines[0] and "cicada_save_url(url)" in lines[0]
    assert skill_catalog.bridge_lines("codex", home=home) == []
    assert skill_catalog.bridge_lines("generic", home=home) == []
    _skill(home, ".claude/skills", "literature-review")
    both = skill_catalog.bridge_lines("claude-code", home=home)
    assert len(both) == 1 and "are installed" in both[0], "one line per bridge key"
```

and append:

```python
def test_the_video_and_meeting_bridges_are_active_and_documents_is_not():
    """R-B14: the watch record (G140) and speaker-aware evidence (G134) shipped, so
    these bridges name tools that work; nothing yet says who wrote a document."""
    active = {e["id"]: (e["bridge"] or {}).get("active") for e in SKILLS}
    assert active["watch"] is True
    assert (active["wispr-flow"], active["granola"], active["transcribe"]) == (True, True, True)
    assert active["pdf"] is False
    assert set(skill_catalog.BRIDGE_TEXT) == {"papers", "video", "meetings"}


def test_a_watch_skill_gets_the_watch_record_line(tmp_path):
    home = tmp_path / "h"
    _skill(home, ".claude/skills", "watch")
    (line,) = skill_catalog.bridge_lines("claude-code", home=home)
    assert "`watch` is installed" in line and "`cicada_record_watch(url, summary, excerpts)`" in line


def test_a_transcription_skill_gets_the_speaker_line(tmp_path):
    home = tmp_path / "h"
    _skill(home, ".codex/skills", "transcribe")
    (line,) = skill_catalog.bridge_lines("codex", home=home)
    assert "`cicada_save_episode(content, title)`" in line
    assert "speaker:<name>:" in line and "never `user:`" in line


def test_a_meeting_saved_the_bridges_way_is_never_the_persons_words():
    """The line's promise, checked against the one marker grammar (R-N2)."""
    from api.services import evidence

    body = "speaker:Alex Example: we ship alpha-project on Friday\nspeaker:unknown: sounds good"
    assert {evidence.speaker_kind(body, 0), evidence.speaker_kind(body, body.index("sounds"))} == {"speaker"}
```

In `test_handshake_bridges.py`, add (with `from _synthetic_bank import _bank, _ok_repo, _settings`
and `from api.services import state_dictionary` in its imports):

```python
def test_all_three_real_bridge_lines_fit_the_budget(tmp_path, monkeypatch):
    """R-B14 makes three keys live; the primer must still carry all three."""
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    memory = _bank(tmp_path)
    state_dictionary.refresh(memory, _settings(memory), force=True, repo_resolver=_ok_repo)
    lines = tuple(text.format(names="`example-skill` is") for text in skill_catalog.BRIDGE_TEXT.values())
    text = handshake.build(state_dictionary.read_state(memory), variant="claude-code", bank="memory",
                           tz="Europe/Madrid", bridges=lines)
    assert len(lines) == 3 and all(line in text for line in lines)
    assert len(text) // 4 <= handshake.MAX_TOKENS
```

Run → the catalog assertions and the two line tests fail. That is the red.

- [ ] **Step 2: Catalog + text.** In `recommended_skills.json`, set `"active": true` on lines 36
(`watch`), 70 (`wispr-flow`), 84 (`granola`) and 158 (`transcribe`); leave 128 (`pdf`) `false`.
`skill_catalog.py`, docstring bullet at `:20-23` becomes:

```python
- a handshake line names only a tool that exists (R12), for an ACTIVE bridge.
  The video bridge names `cicada_record_watch` (G140), and the meeting bridge
  names `cicada_save_episode` with `speaker:<name>:` lines — the one marker
  grammar that files a colleague's words as `speaker` (G134) — never `user:`,
  since an agent cannot know the person's own speaker names (F2-back R-B14).
  Documents stay off: nothing yet says who wrote a document, and an unmarked
  episode reads as the person's own words (R-O28's hazard).
```

`BRIDGE_TEXT` becomes:

```python
#: Handshake text per ACTIVE bridge key; `{names}` becomes "`a` is" / "`a`, `b` are".
#: Arguments are plain names — `test_skill_catalog`'s R12 check splits on commas.
BRIDGE_TEXT: dict[str, str] = {
    "papers": "- Papers: {names} installed. After you look a paper up, save the one you relied on with "
              "`cicada_save_url(url)` so it joins the person's memory.",
    "video": "- Videos: {names} installed. After you watch a video the person asked about, record it with "
             "`cicada_record_watch(url, summary, excerpts)` — a faithful summary and a few short timed "
             "quotes in the video's own words, never a transcript.",
    "meetings": "- Meetings: {names} installed. To keep a meeting, save it with "
                "`cicada_save_episode(content, title)`, one line per utterance written "
                "`speaker:<name>: words` (`speaker:unknown:` when you can't tell) — never `user:`, so "
                "nobody else's words are filed as the person's.",
}
```

- [ ] **Step 3: Green.** `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_skill_catalog.py api/tests/test_skills_router.py api/tests/test_handshake_bridges.py api/tests/test_handshake_r12.py api/tests/test_handshake.py api/tests/test_mcp_handshake.py -q -p no:cacheprovider` → 0 failures.
(`scripts/verify-skills.sh` re-checks upstream pins over the network; no pin changed, so it is not
part of this task.)

- [ ] **Step 4: Docs.** `CLAUDE.md`, "Settings → Skills (G138)" — replace the final sentence ("The
handshake gains a capability line only for an installed, active bridge whose tool exists; the video
and meeting bridges stay inactive until …, both of which have landed (G140, G134).") with:

```markdown
The handshake gains a capability line only for an installed, active bridge whose tool exists: papers
(`cicada_save_url`), video (`cicada_record_watch`) and meetings (`cicada_save_episode`, one
`speaker:<name>:` line per utterance, never `user:`) are active; documents stays off until something
says who wrote a document (F2-back R-B14).
```

TODO F2-back list, append:

```markdown
- The video and meeting skill bridges are active (`cicada_record_watch`; `cicada_save_episode` with
  `speaker:<name>:` lines, never `user:`); documents stays off (R-B14).
```

`memory-evolution.md` G138: replace `**Pending bridges:** `watch → cicada_record_watch` (Track Q);
meetings and documents → `cicada_save_episode` once speaker-aware evidence lands (Track N, R-N2) —
today an agent-saved episode files someone else's words as the owner's.` with
`**Bridges (F2-back R-B14):** `watch → cicada_record_watch` and meetings → `cicada_save_episode`
(one `speaker:<name>:` line per utterance, never `user:`) are active; documents stays off — no
evidence kind names a document's author, and an unmarked episode reads as the owner's.`

- [ ] **Step 5: Full suite, then commit.**

```bash
cd <worktree> && git add api/data/recommended_skills.json api/services/skill_catalog.py \
  api/tests/test_skill_catalog.py api/tests/test_handshake_bridges.py CLAUDE.md docs/goals/TODO.md \
  docs/goals/memory-evolution.md
git commit -m "feat(skills): video and meeting bridges active; documents stays off (R-B14, G138)

cicada_record_watch (G140) and speaker-aware evidence (G134) have landed, so the
watch and meeting bridges name tools that work. The meeting line asks for
speaker:<name>: lines and never user:, since an agent cannot know the person's
speaker names; documents stays off until something names a document's author.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Status reads tell the truth — tunnels outside launchd's PATH, and `next_at` pinned (R-B15 · R-B16)

**Files:**
- Modify: `api/remote/reach.py:1-10` (docstring), `:64-66` (`detect`), new `TUNNEL_BIN_DIRS`,
  `_is_executable`, `find_tool`
- Test: `api/tests/test_remote_reach_paths.py` (new); `api/tests/test_state_wiring.py` (two tests)
- Docs: `CLAUDE.md` (the remote connector paragraph), `docs/goals/TODO.md` (the list's last line,
  the G125 disclosure at `:331-339`)

**Interfaces:**
- Produces `reach.TUNNEL_BIN_DIRS`, `reach.find_tool(name, *, which, exists) -> str | None`;
  `detect`'s keyword `exists` now defaults to an executable-file check.
- Consumes nothing new.

- [ ] **Step 1: Failing tests** — `api/tests/test_remote_reach_paths.py`:

```python
"""F2-back R-B15 — a tunnel installed the normal way is found under launchd's
bare PATH. Detection only: nothing is started, stopped or configured (G135)."""
from __future__ import annotations

from types import SimpleNamespace

from api.remote import reach


def _tool(folder, name, *, executable=True):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    if executable:
        path.chmod(0o755)
    return path


def _stopped(argv, **kw):
    return SimpleNamespace(returncode=1, stdout="", stderr="")


def _bare(monkeypatch, tmp_path, dirs):
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.setattr(reach, "TUNNEL_BIN_DIRS", tuple(dirs))
    monkeypatch.setattr(reach, "TAILSCALE_APP_CLI", str(tmp_path / "no-app" / "Tailscale"))


def test_the_standard_folders_are_the_ones_installers_use():
    assert reach.TUNNEL_BIN_DIRS == ("/opt/homebrew/bin", "/usr/local/bin", "~/bin", "~/.local/bin")


def test_ngrok_under_a_bare_path_is_found_in_a_standard_folder(tmp_path, monkeypatch):
    brew = tmp_path / "brew-bin"
    _tool(brew, "ngrok")
    _bare(monkeypatch, tmp_path, [str(brew)])
    found = reach.detect(8765, run=_stopped)
    assert found.ngrok is True and found.tailscale == "missing"


def test_tailscale_from_a_standard_folder_is_asked_for_its_funnel_and_nothing_else(tmp_path, monkeypatch):
    local = tmp_path / "local-bin"
    cli = _tool(local, "tailscale")
    _bare(monkeypatch, tmp_path, [str(local)])
    calls = []

    def run(argv, **kw):
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout="{}", stderr="")

    found = reach.detect(8765, run=run)
    assert calls == [[str(cli), "funnel", "status", "--json"]]
    assert (found.tailscale, found.ngrok) == ("no-funnel", False)


def test_a_home_bin_is_searched_with_the_tilde_expanded(tmp_path, monkeypatch):
    _tool(tmp_path / "bin", "ngrok")
    _bare(monkeypatch, tmp_path, ["~/bin"])
    monkeypatch.setenv("HOME", str(tmp_path))
    assert reach.detect(8765, run=_stopped).ngrok is True


def test_a_file_that_is_not_executable_is_not_a_tool(tmp_path, monkeypatch):
    brew = tmp_path / "brew-bin"
    _tool(brew, "ngrok", executable=False)
    _bare(monkeypatch, tmp_path, [str(brew)])
    assert reach.detect(8765, run=_stopped).ngrok is False
```

Append to `test_state_wiring.py` (it already imports `pytest`, `datetime`, `timedelta`,
`timezone`, `TestClient`, `main` and `markdown_parser`, and defines `_git`):

```python
@pytest.mark.parametrize("mode", ["manual", "daily", "interval", "after_import"])
def test_state_and_status_name_the_same_next_run_in_every_mode(api_bank, mode):
    """F2-back R-B16: `/state`'s `sleep.next_at` and `/status`'s `nextSleepAt` are
    one formula with one set of inputs (Track P R6, `7d1de42`) in all four modes.
    The cycle is an hour old, so `interval` anchors on it rather than flooring at
    now; `after_import` has a waiting episode, so it names an instant."""
    from api.models.schemas import ScheduleConfig
    from api.services import episode_ids, sleep_scheduler

    an_hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(timespec="seconds")
    _git(api_bank, "commit", "-q", "--allow-empty", "--date", an_hour_ago, "-m", "Sleep cycle 2026-09-22")
    markdown_parser.write(
        api_bank / "episodes" / "ep_2026-09-22_001.md",
        {"id": "ep_2026-09-22_001", "timestamp": episode_ids.utc_now_iso(),
         "processed": False, "origin": "claude-code", "title": "Alpha project sync"},
        "user: ship alpha-project",
    )
    sleep_scheduler.save_schedule(api_bank, ScheduleConfig(mode=mode, hour=3, minute=0, interval_hours=6))
    with TestClient(main.app) as client:
        state_next = client.get("/state").json()["sleep"]["next_at"]
        status_next = client.get("/status").json()["nextSleepAt"]
    if mode == "manual":
        assert (state_next, status_next) == (None, None)
        return
    gap = abs(datetime.fromisoformat(state_next) - datetime.fromisoformat(status_next))
    assert gap <= timedelta(seconds=2), (state_next, status_next)
    if mode == "interval":
        assert datetime.fromisoformat(state_next) > datetime.now() + timedelta(hours=4)


def test_after_import_with_nothing_waiting_has_no_next_run_on_either(api_bank):
    from api.models.schemas import ScheduleConfig
    from api.services import sleep_scheduler

    sleep_scheduler.save_schedule(api_bank, ScheduleConfig(mode="after_import", hour=3, minute=0))
    with TestClient(main.app) as client:
        assert client.get("/state").json()["sleep"]["next_at"] is None
        assert client.get("/status").json()["nextSleepAt"] is None
```

Run: the reach tests fail (`TUNNEL_BIN_DIRS` does not exist). The two `/state` tests are expected to
**pass on first run** — R-B16 says they pin code `7d1de42` already fixed. If either fails, stop and
report: the premise that `/state` is calibrated is then wrong, and this task grows.

- [ ] **Step 2: `reach.py`.** Replace the docstring's second paragraph opening ("Tailscale:
`shutil.which` (the launchd plist's PATH has /opt/homebrew/bin and /usr/local/bin) or the app
bundle's own CLI.") with:

```python
Tailscale: on PATH, in a standard install folder (`TUNNEL_BIN_DIRS`), or the app
bundle's own CLI — an older LaunchAgent's PATH is launchd's bare one, and
`install.sh` never rewrites a plist behind a running backend (F2-back R-B15).
```

Above `detect`:

```python
#: Where Homebrew (Apple silicon, then Intel) and a hand-installed binary put
#: `ngrok` and `tailscale` (F2-back R-B15). Under an older LaunchAgent's bare
#: PATH, `shutil.which` alone reported ngrok missing on a Mac where it was
#: installed — the same trap `connections.base._CLI_FALLBACK_DIRS` closed for
#: the engine CLIs. Reach keeps its own list so detection stays injectable.
TUNNEL_BIN_DIRS: tuple[str, ...] = ("/opt/homebrew/bin", "/usr/local/bin", "~/bin", "~/.local/bin")


def _is_executable(path: str) -> bool:
    return os.path.isfile(path) and os.access(path, os.X_OK)


def find_tool(name: str, *, which=shutil.which, exists=_is_executable) -> str | None:
    """``name`` on PATH, else in :data:`TUNNEL_BIN_DIRS`. Looks; never runs it."""
    found = which(name)
    if found:
        return found
    for folder in TUNNEL_BIN_DIRS:
        candidate = os.path.join(os.path.expanduser(folder), name)
        if exists(candidate):
            return candidate
    return None
```

`detect`'s signature and first two lines become:

```python
def detect(port: int, *, which=shutil.which, run=subprocess.run, exists=_is_executable) -> Reach:
    ngrok = bool(find_tool("ngrok", which=which, exists=exists))
    tailscale = find_tool("tailscale", which=which, exists=exists) or (
        TAILSCALE_APP_CLI if exists(TAILSCALE_APP_CLI) else None)
```

(`test_remote_router.py:167-181` passes `exists=lambda p: False` and a `which`, so it stays hermetic.)

- [ ] **Step 3: Green.** `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_remote_reach_paths.py api/tests/test_remote_router.py api/tests/test_state_wiring.py api/tests/test_status_settings_fields.py api/tests/test_sync.py -q -p no:cacheprovider` → 0 failures.

- [ ] **Step 4: Docs.** `CLAUDE.md`, "The remote connector (G135)" — replace
"`GET /remote/status` only detects one." with "`GET /remote/status` only detects one — on PATH or in
the standard install folders, since an older LaunchAgent's PATH is bare (F2-back R-B15)."

`docs/goals/TODO.md`, in the G125 entry under Shipped, replace everything from
`**Disclosed gap:** \`GET /status\`'s \`next_sleep\`` through `fold in alongside the next \`/state\`
touch.` with:

```markdown
**Closed:** `GET /state`'s `sleep.next_at` is calibrated with the same inputs as `/status`'s
"Next run" (Track P R6, `7d1de42`) and pinned against it in all four modes (F2-back R-B16).
```

TODO F2-back list, append the last two lines:

```markdown
- `GET /remote/status` finds ngrok and Tailscale in the standard install folders, not only on
  launchd's PATH (R-B15); `/state`'s `sleep.next_at` was already calibrated (Track P) and is now
  pinned against `/status` in all four modes (R-B16).
- Baselines: backend **N passed** on `fix/backend-batch-2` — the orchestrator measures and fills this.
```

- [ ] **Step 5: Full suite, then commit.**

```bash
cd <worktree> && git add api/remote/reach.py api/tests/test_remote_reach_paths.py \
  api/tests/test_state_wiring.py CLAUDE.md docs/goals/TODO.md
git commit -m "fix(remote): find tunnels outside launchd's PATH; pin /state next_at in every mode (R-B15, R-B16)

Under an older LaunchAgent's bare PATH, GET /remote/status said ngrok was not
installed. Detection now also looks in the standard install folders (detection
only; G135). /state's next_at was already calibrated by Track P; it is now pinned
against /status in all four schedule modes and TODO's stale disclosure is closed.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

## Not in scope

These are listed so a reviewer does not read an absence as an oversight.

- **Cross-process serialisation** beyond git's own `index.lock` and R-B2's retry. That covers the
  stdio MCP server's `agent_commits`, a person's terminal and an Obsidian git plugin (R-B1). Nor
  **un-staging after a refused commit**: `git reset` needs the same lock that just refused.
- **Other `git add -A` writers sweeping kept paths before the retry.** A feed or calendar poll, a
  Telegram capture, a Notes sync or an entity edit can still land between a refusal and the
  writer's next run. Only Sleep, the most frequent sweeper, is pre-empted (R-B5). Also not here: the
  **ledger for other scoped writers** (`bookmark_sync`, `media_ingestor`, `link_enrichment`,
  `agent_commits`, `state_dictionary`). They get the lock and the retry only.
- **A 409 on a rules save while Sleep runs** (declined, R-B6). The in-flight race it would target
  exists on the app's re-post path too, and a cycle's `git add -A` can sweep any writer's files
  written between its start and `_finalize` (TODO's G135 note, R-R27).
- **Rewriting the stored span kind** of beliefs Sleep formed before a rules change (R-B8; Open
  questions).
- **App follow-ups for the app track.** Name `agent` as "An agent", with a generic agent mark, in
  `OriginIconography`. `ProvenanceSummaryTests.swift:64` still uses the placeholder as a `model`
  fixture; it is app test data and harmless. `updateAgentGlobs` still re-posts every file, which is
  now a no-op.
- **A free-text `CICADA_SESSION_HARNESS` value** outside the harness table stays `model` (R-B9).
- **The `documents` bridge** (R-B14). Nor **a `CICADA_NGROK_CLI` override**, or merging reach's list
  into `connections.base.resolve_binary` (R-B15).
- **Anchor stripping anywhere but paper claims.** The episode text, Sleep's extractions and
  Telegram's reason are untouched. So is **re-minting paper claim ids** from cleaned words (declined,
  R-FX5 / R-B12). Nor a **stored slot** on paper claims: without one, an edited annotation whose raw
  words had anchors closes with `superseded_by: None` (R-B12's disclosed consequence). It never
  links the wrong successor.
- **Any code change to `/state`'s `next_at`** (R-B16).
- **Re-running `scripts/verify-skills.sh`.** No pin changed.

## Merge notes

Checked on 2026-09-23 with `git diff dev...<branch>` over every local branch ahead of `dev`. None
touches a file this plan edits. The app redesign track edits `app/` only, and this track edits none
of it. If a sibling branch lands a new `subprocess.run(["git", "add"|"commit", …])` first, the Task 1
lint fails on the merge. The fix is to route it through `git_service.commit_paths_sync`, not to relax
the lint.

## Verification the orchestrator runs at the end

1. `cd <worktree> && api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider` → **0
   failures**. If the order-dependent provenance case is the only red, re-run it alone and report both
   results. Record the passed count in TODO's F2-back "Baselines" line.
2. **Lint self-test:** temporarily add `subprocess.run(["git", "commit", "-m", "x"])` to the end of
   `api/services/sync_state.py`. `api/tests/test_git_write_lock.py::test_no_module_spawns_a_git_write_outside_git_service`
   must fail. Revert.
3. `cd <worktree> && git diff dev --stat -- app/` → empty.
4. **Live — the orchestrator only.** The implementing engineer never runs this step: it reads the
   live bank's git log and `~/.cicada/api_token`, which the Global Constraints forbid them. (The
   orchestrator restarts the backend with
   `launchctl kickstart -k gui/$(id -u)/com.cicada.backend`). Print counts and subjects only, never
   paths, names or claim text:
   - The startup log shows the paper claim-text repair as numbers only, or nothing on a bank without
     noisy claims. `git -C <bank> log -3 --format='%s | %(trailers:key=Cicada-Author,valueonly)'`
     shows `Repair paper claim text … | cicada` when it ran. A second restart adds no commit.
   - `curl -s -H "Authorization: Bearer $(cat ~/.cicada/api_token)" localhost:8000/remote/status | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["ngrokInstalled"], d["tailscale"])'`
     → `True` on this Mac (ngrok installed), under the unchanged launchd plist.
   - `curl -s -H "Authorization: Bearer $(cat ~/.cicada/api_token)" localhost:8000/contributors | python3 -c 'import json,sys; rows=json.load(sys.stdin); rows=rows.get("contributors", rows) if isinstance(rows, dict) else rows; from collections import Counter; print(Counter(r["kind"] for r in rows))'`
     → a `harness` bucket where agent commits exist, and no row whose author is `mcp-agentic-write`.
   - In the app, press "Sync now" on a watched folder while a paper-details run is going. Then
     `git -C <bank> status --porcelain | wc -l` → `0`, and
     `ls <bank>/.git/cicada-pending-commits.json 2>/dev/null | wc -l` → `0`.
   - In the app, change a watched folder's "written by an agent" rule. The newest commit is
     `Folder settings (…) | user`, and its manifest lines say `trigger: folder/authorship`. Print the
     subject, author and a count of `episodes/` lines only.
   - `curl -s -H "Authorization: Bearer $(cat ~/.cicada/api_token)" "localhost:8000/handshake?client=claude-code" | python3 -c 'import json,sys; t=json.load(sys.stdin)["text"]; print("Videos:" in t, "Meetings:" in t)'`
     → `True` for Videos only if `watch` is installed on this Mac. Either answer is correct; report it.
5. **PR body must state:**
   - One git writer per bank, with the reproduction (5/5 trials on a synthetic bank) and the rulings
     R-B1…R-B5.
   - No LLM in any path. The one migration is engine-free and marker-guarded.
   - No ETag component, Store domain or endpoint added. No `app/` file touched. Three ETags fold
     one shape tag (`AUTHOR_SHAPE`) because their bodies changed for the same inputs (R-B10).
   - The `harness` kind is a VALUE the app already decodes, not a new shape.
   - R-B12's disclosed consequence (an edited noisy annotation closes without `superseded_by`).
   - The open question below.

## Open questions (the owner's alone)

1. **A belief Sleep already formed from a file you later mark as agent-written** keeps the span kind
   ("You said") and trust it was minted with (R-B8). Keep it as history (the default this track
   ships)? Or should a rules change also withdraw or re-label those beliefs? That would mean
   re-judging them, not just relabelling a span.
