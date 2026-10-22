# Cicada — priorities and handoff

**Updated 2026-10-06. Today’s delivery priority:** G182 — make GitHub releases work today, automatically keep the released version/`main`/website links aligned, and complete the per-integration post-consolidation read/contribute checks. Release work must clear applicable integrity/packaging checks and report blocked or unsupported integrations honestly. [Release requirements](../specs/2026-10-06-release-and-integration-acceptance.md).

**Memory-quality pickup:** fix the relevant G183/G177 write-integrity gaps, repair G185’s reported test regression, then use [the first-memory-trial runbook](2026-10-06-first-memory-trial.md). Do a small trial before a full user-started drain. The immediate product question is whether asking ordinary questions about your life feels useful and trustworthy.

[Implementation review: every G ID](BACKLOG_IMPLEMENTATION_REVIEW.md) · [Active reasoning by priority](memory-evolution.md) · [Completed work](DONE.md) · [Reference context / original prompts](BACKLOG_CONTEXT.md) · [Working method](working-method.md) · [Cognition comparison](../research/2026-10-06-agent-memory-repo.md) · [Source/video gaps](../research/2026-10-06-source-refresh-and-video-gaps.md) · [Provider/source modularity](../specs/2026-10-06-provider-and-ingestion-modularity.md) · [Benchmark rebuild](../specs/2026-10-06-system-benchmark-rebuild.md)

## Current state and evidence

- **2026-10-22 — the dev auto-update runs on a Linux server too (G181; branch `feat/linux-dev-autoupdate`).**
  `scripts/dev/install-auto-update.sh` branches on `uname`: on Linux it writes a systemd user timer
  (`cicada-dev-autoupdate.timer`, `OnCalendar=*:0/5`, `Persistent=true`) and its oneshot service; `--uninstall` removes
  either platform's job. `auto-update.sh` on Linux keeps every guard (on `dev`, clean, ff-only, waits out Sleep, the
  installed stamp), restarts `cicada-backend.service` (`CICADA_BACKEND_UNIT`) when runtime code moved, re-syncs a server
  venv through `sync-server-env.sh` (a full venv with `uv sync`), and has no app to build. macOS unchanged.
  `api/tests/test_dev_auto_update.py` stubs `uname` (CI runs on Linux) and covers both.
  Follow-up (review of #400): on Linux the stamp moves only when the sync and the restart both worked (a failure
  retries next tick), and the Sleep check asks the port and home the backend unit names. the dev server runs it
  (`cicada-dev-autoupdate.timer`, first run 2026-10-22 moved the stamp to d25ba62).
- **2026-10-22 — the Skills inventory sees Claude Code's plugins and tags every skill's kind (G201 slice (a), TODO
  ruling 35; branch `feat/skills-see-plugins`).** `skill_plugins` reads Claude Code's installed plugins read-only from
  its own files (`installed_plugins.json` v2 and the older shapes, the user `enabledPlugins`, each plugin's manifest and
  its skills' SKILL.md frontmatter, `disable-model-invocation` included); missing or corrupt files are an empty answer,
  an install path outside `.claude/plugins` or a manifest path out of the plugin is never followed, a project-scoped
  switch is null (its project's settings are never opened), and nothing toggles a plugin (`canToggle: false`).
  `skill_kind` tags every skill without a model: third-party and plugin skills `generic`, a candidate (noticed, held,
  drafted, published draft) `about-you` when its evidence pages or `[[links]]` name a person or project page or the
  owner's, else `unknown`; the person's flip is `PUT /skills/kinds`, stored by `skill_store.set_kind` in
  `$CICADA_HOME/skills/kinds.json`. `GET /skills` and `cicada_skills` gain `plugins`, `kind*` and `weight` (additive;
  per agent the skills loaded and an estimate of description tokens, characters/4, no cap enforced). The Skills page
  shows a Kind column, the Plugins group and one weight line (DR-59's dated exception, ruling 35 §6). Tests:
  `test_skill_plugins.py`, `SkillsPageTests`. Pick up: slice (b), the Stop hook keeping the names of invoked skills.
- **2026-10-22 — MCP hygiene from the Hyrum audit (branch `fix/mcp-hygiene`; G199's two integrity cases, G200 A8,
  A10, A11, ruling 34's episode-id day).** `cicada_write_claim` refuses an `observer` outside its pattern and
  `cicada_save_episode` refuses empty `content`, in the tool bodies, so stdio, `/tools/call`, the remote connector and
  the command line refuse alike (`code: refused`, nothing written). The advertised `observer` pattern no longer names
  the legacy observer value; the body still accepts it. Stdio answers `ping`, `-32700` and `-32602`, and annotates its
  read tools from `catalog.READ_TOOLS`. `SKILL.md` (and the plugin copy) and the type-hub blurb no longer teach a stale
  layout, "never edit" or a file path. Ruling 34: the two hook writers mint the local day (`episode_ids.id_day`); a client
  posts its own `utc_offset_minutes` (additive on `/capture/session` and `/capture/turn`); `ask_sources.said_day` and
  `benchmarks/hard_questions` read the stamp in the person's zone; ids are never renamed. The golden fixture did not
  change. Left for G199 proper: `isError` for refusals, `structuredContent`, validating every argument. Found, not in
  scope: Sleep's `source_dates.episode_day` still dates a conversation by its UTC stamp's first ten characters.
- **2026-10-21 — the seven backend failures on dev before 0.6.0 (branch `fix/suite-0.6`).** The full suite on
  `24a419a7` gave 7 failed, 10,864 passed. Two were code: the entity card opened the claims ledger through
  `quiet_pages.page_is_quiet` (#391) because `bank_index.file` parsed with the ledger fold — it now reads the header
  exactly as `bank_index.files` does, so no `bank_index.file` caller opens a ledger or carries the fold's read mark;
  and `handshake.claude_skill` (#364) named Claude Code's skills folder itself — the path now comes from
  `skill_folders.has_skill` (read-only), so `skill_store` stays the only module that names that folder and writes. The
  plugin got `.claude-plugin/icon.png` (the app icon), since the installed `claude plugin validate` now warns
  `ICON_MISSING`. Four tests were stale: the scheduled billing preview follows ruling 4c (a plan unless the person's
  switch is off, #360), the writer inventory names #391's `_write_page`, and the video tests take ruling 32's remote
  contract 12 and `cicada_capture_turns`' exemption from the bank write gate (#359).
- **2026-10-21 — The inbox tidy as a trace the coordinator reads, then a vetted apply (owner rule 2026-10-20;
  branch `feat/tidy-trace`).** A counts-only dry run once let 8 wrong conflict settles through. `api/scripts/
  inbox_tidy_trace.py trace --bank <path> --out <file> --engine plan --model haiku [--kind merge_suggestion]` runs the
  tidy's dry run in process and writes one 0600 JSONL row per question (id, kind, the two names, merge / keep_apart /
  settle / leave, the judge's confidence, a one-line reason) outside every bank; `--engine plan` never resolves or
  calls the bank's configured engine. `… apply --vetted <file>` sends the kept rows to `POST /inbox/tidy/apply`, which
  settles each exactly as traced as Sleep's undoable commit, only while the question and its pages are unchanged.
  Detail: `features.md`, "The coordinator's trace and vetted apply". Tests: `test_inbox_tidy_trace.py`. Pick up: the
  coordinator traces the owner's "Possible duplicate" questions (#389's empty-description cause) and reads every row.
- **2026-10-21 — a merge or rename keeps what the person gave the page (G147, G146; branch `feat/next-row`).**
  `entity_merge.merge_entities` unions both pages' `kept_on` (`decay_policy.merged_keeps`), so a keep answered on the
  absorbed page still slows the merged page's fade; it carries the person's picture choice when the winner has none
  (the upload's file moves to the winner's id) and removes a loser upload the winner's own choice outranks;
  `rename_references` moves an upload's file with its page. The footprints name the picture files
  (`entity_picture._merge_plan`, `rename_footprint`), so the dedup sweep's transaction and the placeholder repair's
  dirty check cover them. Every merge door is driven (`test_merge_edges.DOORS`). Tests:
  `test_merge_keeps_person_marks.py`. Pick up: review and merge; tonight's inbox tidy merges then keep both.
- **2026-10-20 — Contacts as a seed; imported-only pages stay quiet (ruling 33, G154; branch `feat/people-seed`).**
  Unmatched address-book cards wait in `$CICADA_HOME/people/<bank>/contacts.json` (`people_directory`, shared with
  LinkedIn; 0600); a person's first conversation mention naming exactly one waiting card promotes on its own and the
  page is born with the card's name, sources and photo (`entity_resolver._card_for`, `contacts_local.seed_page`);
  Sleep's tail rematches the rest (`_rematch_contacts_safely`). The app marks the "me" card (`isMe`, that card only),
  which goes to the owner's page. `quiet_pages` derives *quiet* (an imported page not mentioned yet): `GraphNode.quiet`
  (`NODE_SHAPE` `+quiet`), `GET /entities/{id}`'s `quiet`, hidden from every inbox reader; the app dims quiet nodes
  (faint fill, type-hue ring) and Clusters rows. Tests: `test_people_seed.py`, `QuietPagesTests`. Pick up: the owner
  connects Contacts on his bank (0 of 273 people matched today) and reads one night's Sleep log for the promoted count.
- **2026-10-20 — Sleep asks about half the model calls per conversation (branch `perf/sleep-calls`).** A
  14-conversation haiku night made 574 calls (disambiguation 268, merge 116, conflict 110, extraction 48). Stage 2's
  judge now weighs up to 6 of a name's candidates in one call and Stage 3 checks up to 5 pages for contradictions in
  one call (a lone one keeps the old prompt); and the judge now reads the extraction's `summary` — it was reading
  `description`, which Stage 1 almost never fills, so first-name mentions became "Possible duplicate" questions.
  Synthetic night (`benchmarks/scale/sleep_calls.py`, 8 conversations, plan + haiku, replayed prompts): 16.0 → 11.4
  calls a conversation, pages identical under batching alone; projected ~280–320 calls for the owner's night.
  Detail: `capture-and-sleep.md`, *Fewer calls per conversation*. Tests: `test_sleep_call_batching.py`,
  `test_entity_resolver_concurrency.py`, `test_conflict_resolver_concurrency.py`. Pick up: the coordinator reads the
  next scheduled night's `llm_call` counts by stage and the inbox's new "Possible duplicate" count.
- **2026-10-20 — Ask infers implied facts and reads Spanish conversations for an English question (G148; branch
  `feat/ask-gaps`).** A fact-worded question the record only implies (a state or country from a city, a holiday, a
  described thing's name, a yes or no about someone, an age, a preference) gets a stricter note: a stated line wins,
  else "probably …, because …", a loose link still declines. An English question whose nearest conversations are in
  Spanish goes by meaning (the record's language decides, never missing words). The meaning leg ranks turns without
  the speakers' names, from two passages a conversation. On haiku, 3 runs: implied facts 4.67 → 12 of 15 (better,
  p = 0.016; adversarial 2/3 both sides); English over Spanish, behind a per-model score floor so a never-said
  question reads as on dev (review): 7 → 11 of 14, abstentions 7/7 both sides (p = 0.125, small set). Fixture
  `benchmarks/public/fixtures/locomo-es-turns.json` (`--turns`). Pick up: the coordinator's `--compare` on the
  owner's two sets — every Spanish prompt changed. Detail: `docs/research/2026-10-17-memory-benchmarks.md`.
- **2026-10-20 — Ask reasons a judgement from the record and answers Spanish by meaning (G148; branch
  `feat/ask-infer-es`).** A judgement question ("would <name> likely …", "¿es probable que …?") gets a note to answer
  "probably …, because …" from the record; a recorded fact still declines. A Spanish question goes by meaning: the
  search model's nearest passages and ranked claims/items reach the prompt (Spanish answer turns 8 → 33 of 74 on
  LoCoMo; English 38). On haiku: open-domain judgement questions 17 → 26 of 42, LoCoMo in Spanish 50.0 → 67.5,
  Spanish adversarial 10 → 9 of 10 (an honest decline judged wrong); every other English prompt byte-identical.
  `--questions benchmarks/public/fixtures/locomo-es.json` runs the Spanish set. Pick up: the coordinator's `--compare`
  on the owner's two sets with haiku. Detail: `docs/research/2026-10-17-memory-benchmarks.md`.
- **2026-10-20 — the owner's answer eval runs each question several times and judges a change on majorities (G148;
  branch `feat/eval-repeats`).** Four runs of the owner's 60 questions on near-identical code scored 46, 44, 42, 42 with
  13 questions flipping, so one run cannot judge an Ask change (#365 read −2; its revert did not restore the number).
  `benchmarks/answer_eval.py --repeats N` (default 3) answers and judges every question N times into one `--out`,
  resumable per (question, run), failed pairs re-asked; the summary gives each measure's mean and min–max across runs,
  overall and per tag, and always right / always wrong / flips (ids only). `--compare A.jsonl B.jsonl` (no calls) is
  the accept rule: B differs only when the exact sign test on questions whose majority verdict changed gives p < 0.05,
  Δ mean correct exceeds the wider min–max of either file, **and** both move the same way; a file is never resumed
  under other run settings, and `--fresh` starts it over. `claude -p` has no temperature/top-p/seed; the model
  the plan reported, the CLI version and `--effort` (opt-in pin; drops an inherited `CLAUDE_CODE_EFFORT_LEVEL`) are
  recorded and compare flags any mismatch. Tests: `test_answer_eval_repeats.py`, `test_public_benchmark.py`. Pick up:
  the coordinator re-runs the owner's eval with `--repeats 3` on dev as the baseline file every Ask change compares to.
- **2026-10-19 — plan-first engines; the inbox stops asking what a web search can answer (rulings 4c, 27b, 31; branch
  `feat/plan-first-inbox`).** Scheduled runs use the plan unless the person turned it off; Auto (the new default) never
  falls to a metered key; the web lookup runs on every plan run and the backlog gets a one-off sweep
  (`POST /inbox/web-check`); Cicada's own settings are never asked (`own_settings`). Tests: `test_plan_first_inbox.py`,
  `test_engine_select.py`, `test_server_readers.py`. Pick up: the coordinator runs the sweep's dry run on the owner's
  bank (`api/.venv/bin/python -m api.scripts.web_check_dry_run --bank <path> --census`, then `--limit 20`), reports the
  counts, then `POST /inbox/web-check?dryRun=false` on the running backend; checks the owner's own engine choice still
  says what he meant (an explicit OpenRouter pick stays OpenRouter).
- **2026-10-19 — Cicada as a Claude Code plugin (owner 2026-10-19; G49's plugin half, G105, G149; branch
  `feat/claude-code-plugin`).** Rule recorded in CLAUDE.md: the plugin is the canonical Claude Code door, `install.sh`
  the canonical machine install. The repo is its own marketplace (`.claude-plugin/marketplace.json`, plugin
  `./plugins/cicada`, id `cicada@cicada`): the MCP server, the `cicada` skill (a byte copy of `SKILL.md`), and the
  Stop/PreCompact/SessionEnd capture and SessionStart/UserPromptSubmit recall hooks, all through two POSIX scripts that
  exec the app's `~/.cicada/bin` launchers or a checkout named in the plugin's `cicada_repo` setting. Only when the
  plugin is enabled, installed and able to run a Cicada does `install.sh` stop registering Claude Code's hooks and MCP
  entry and remove its older ones (an enabled plugin that would run nothing keeps them, with a warning; a recall-off
  choice is carried into the plugin's setting); `make doctor` and
  `GET /agents/wiring` (`capabilities.via = "plugin"`) say which door is active. Detail: `mcp.md`, "The Claude Code
  plugin". Tests: `test_claude_code_plugin.py`. Pick up: review and merge; the owner installs it with `/plugin
  marketplace add ~/code/cicada` (dev) or `rorosaga/cicada` after the next release, sets `cicada_repo` if he runs a
  source build, then re-runs `./install.sh` once.
- **2026-10-19 — sign-in for the remote connector, and real-time capture through it (ruling 32, G135, G105; branch
  `feat/remote-oauth`).** `api/remote/oauth.py`: an OAuth 2.1 authorization server on the G135 listener (DCR + CIMD,
  S256 only, consent only in the app, single-use 120 s codes, hour-long access and rotating refresh tokens mapped to
  connector rows, RFC 9207 `iss`, RFC 7009 revocation, rate limits, everything hashed at rest); the 401 now carries
  `resource_metadata`. `cicada_capture_turns` (`record`, remote only) relays each turn through `turn_capture`'s writer
  as a `relay` episode with `evidence_kind: assistant`; `episode_staging` upgrades it in place when the app's export
  arrives. App: *Waiting for your yes* on From anywhere. What the person runs: `docs/connect-remote-apps.md`. Tests:
  `test_remote_oauth.py`, `test_relay_capture.py`, `RemoteConnectorTests`. Pick up: the owner runs a funnel on 8765 and
  adds the connector in claude.ai (web, then phone) and ChatGPT — unverified against the live apps until then.
- **2026-10-18 — Ask over watch-history ranges (ruling 30 follow-up, G71, G94, G118; branch `feat/history-ask`).**
  `watch_history.asked_span` + `summarize`: this/last year, a named year, since/between, the last N days, ever, "the
  most", first/last watch of a named channel — counted from the watched days with no model into one bounded table.
  Only a question with a watch verb, a platform or a channel the record holds reads it (never a bare "video"/"channel").
  The WATCH HISTORY block is headed as computed now and current only through its last watched day; synthesis rule 10
  keeps an earlier note about the system's own state from being repeated as current, never the person's later words. Citations name at most 5 grounding episodes plus `source_episodes_more`.
  `test_sync_watch.py`'s flake was the tests' timing, not the watcher: FSEvents reports the setup's own writes up to
  ~2 s late, and any report seconds late under contention; the tests now wait for an uncounted marker (events arrive in
  order) and drive the ticker's clock instead of sleeping. 5 runs in a row and 15 runs five-at-once green. Tests: `test_ask_watch_ranges.py`. Pick up: review and merge.
- **2026-10-20 — broad public benchmark on the production setup (G148; branch `bench/broad-2026-10-20`).** All 10
  LoCoMo conversations (382 Qs, Sleep `haiku`, EmbeddingGemma 2, answers/judge `sonnet` on the plan): `cicada_ask` J
  74.9 (single-hop 91, temporal 90, multi-hop 65, open-domain 49); full-context control 88.9 vs Ask 77.8 on the same five
  conversations. LongMemEval_S, 100 Qs without Sleep (search leg only), 3 repeats: 66.7 (66–67); multi-session 12.
  Honest: 73 % of misses name the gap, ≈ 2–3.5 % contradict, 1 of 14 abstentions answered. Misses track whether the
  answer turn reached the prompt (J 84 vs 44). 2,349 plan calls. Harness: `--sleep-schedule none`, `--gate`, prompt /
  context-ms / answer-turn fields. Details: `docs/research/2026-10-17-memory-benchmarks.md`, "Broad sample 2026-10-20".
- **2026-10-18 — watch history and export saves are indexed, not consolidated (ruling 30, G71, G94; branch
  `feat/history-index`, not merged).** `history_index` (the one predicate, the dry-run count, the retirement),
  `watch_history.rollup` (a month's summary, no model), `watch_history.lookup` (Ask's read of the record),
  `watch_history.channel_line` (a channel page's derived line), `sleep_cycle._index_without_model_safely` (before the
  freeze) and `_embed_indexed_episodes_safely` (the tail's vector sync). Tests: `test_history_index.py`. Pick up: the
  coordinator runs `api/.venv/bin/python -m api.scripts.history_index_dry_run --bank <path>` on the owner's bank (counts
  only), then the next Sleep run retires the queued days and saves; the first vector sync of ~5.7k episodes runs in
  that run's tail.
- **2026-10-17 — are the answers good? Public benchmarks through Cicada on the plan, and the owner's own eval (G148; branch `feat/memory-bench`).** Survey and recommendation: `docs/research/2026-10-17-memory-benchmarks.md` (LoCoMo with Mem0's J judge first, LongMemEval by type second). `python -m benchmarks.public.run prepare|run|report` runs LoCoMo/LongMemEval end to end (stager → drain → `cicada_ask` → published judge, full-context control, resumable, throwaway marked banks, `claude -p` only). `python -m benchmarks.answer_eval --bank … --questions benchmarks/answer_eval.local.yaml` grades Ask on the owner's bank against facts he writes. First slices: LoCoMo Ask J 52.5 vs full-context 95.0 (40 Qs); LongMemEval oracle 70 vs 85 (20 Qs) — honest gaps, lost detail. Tests: `test_public_benchmark.py`. Pick up: review and merge; the owner writes `benchmarks/answer_eval.local.yaml` and runs it; then the evidence-span Ask experiment on the same checkpointed banks.
- **2026-10-17 — small backend fixes and the LinkedIn photo decision (branch `fix/api-small`).** (1) The closed type
  set: a plain-JSON engine is held only by the prompt's type list, and nothing between extraction and the create branch
  checked the type, so a model's `organization`/`product`/`program` reached pages (3 on the owner's bank).
  `entity_types.producible` now maps it at extraction and again where a page is born (Sleep create branch, inbox
  answer); the person repairs an older bank with `python -m api.scripts.repair_entity_types --bank <path>` (dry run;
  `--list`, `--as <id>=<type>`, `--apply`). (2) `install_predicate_map` reads the runtime map through
  `_read_runtime_map`, the one reader. (3) Parked defects re-checked, all already fixed on dev with tests: media save
  dates (G99d `saved_at`/`content_saved_at`), same-title media pages (`_media_entity_id` URL-hash suffix), and the
  `<name>.com` logo guess (removed in G61 S3-b; `GUESSABLE_TYPES` is now only "types whose own site draws a mark").
  (4) The LinkedIn photo amendment below. Tests: `test_entity_types.py`, `test_predicates_map_cache.py`,
  `test_linkedin_people.py`.
- **2026-10-17 — Sleep tends the inbox, part 3: passing names and label conflicts (ruling 29; branch
  `feat/inbox-sleep-3`, not merged).** `inbox_tend.passing_rule` (`in_passing`: a page-less name said once in passing,
  or a code identifier, closes through the person's own dismiss; never tied to the person's life — relation words,
  first-person lines about people/places/companies, the owner's page, Messages) and `newest_words` / `label_lines`
  (a label-only conflict settled by the person's newest plain statement of one side, located in their own turn,
  dated that day; the conflict judge reads those lines when it is not mechanical). The lexical index is read fresh
  inline (`ensure_fresh(wait=True, max_age_s=0)`) so a just-committed conversation counts. Synthetic backlog (27
  passing names, 15 that must stay, 10 label conflicts): before 0 settled / 52 asked; after 33 settled / 19 asked
  (27 `in_passing`, 6 `newest_words`; stays: 8 a person in the person's own words, 4 named again, 3 Messages, 4 label
  conflicts for the judge). Review fixes (B1, B2): a person said in the person's own turn never closes; company/place
  checks read the turn and its neighbours; the mechanical label path needs the subject in the stating sentence and no
  negation/modal/avoidance on the raw text. Re-review: a relation counts only when a possessive ties it to someone,
  links and metadata lines are never words, a saved item's title/link/byline is never the person's own words, and the
  mechanical label path needs a plain placement right before the label (allowlist; the blocklist stays a second
  guard). Tests: `test_inbox_tend.py` (part 3 block). Pick up: the owner's `inbox_tidy_dry_run --judge`.
- **2026-10-17 — Sleep tends the inbox, part 2 (ruling 29; branch `feat/inbox-sleep-2`, not merged).** What the
  first pass could not reach (owner's judged dry run: 55 conflicts never reached the judge, 69 clarifications never
  tried): label-only conflicts judged through the claims their labels are tied to (`label_matches`, folded words,
  never fuzzy); a page-bound question whose name resolves to no file retires, an unreadable page stays
  (`ask:unreadable_page`); **move 3 — answered already, anywhere in the record** for clarifications, follow-ups and
  conflicts (`said_on_record`, 4 per drain in Sleep, every one in the tidy with `judge=true`); follow-ups settle
  through `progress` as Sleep's, dated the day the person said it. Tests: `test_inbox_tend.py` (part 2 block).
  Pick up: the owner's `inbox_tidy_dry_run --judge` on his bank; if `ask:unreadable_page` shows up in conflicts,
  that is where the 5 "page gone" ones were (a synthetic bank could not reproduce a missing page that dev's
  `_subject_gone` did not already retire).
- **2026-10-17 — Sleep tends the inbox (ruling 29, G21, G113; branch `feat/inbox-sleep`, merged #332).** `inbox_tend`
  (the policy table, the answered-in-conversation read, the duplicate judge, the one writer and its undo), `inbox_actor`
  (who answered: the person's resolvers commit as Sleep's while it is set), `sleep_cycle._tend_inbox_safely` after each
  batch's commit, `POST/GET /inbox/tidy` (dry run by default; counts only) and `api/scripts/inbox_tidy_dry_run.py`, the
  "Settled by Sleep" group beside "Settled by a check" (same list and undo routes, `group: sleep`), `inbox_settled` on
  the Sleep status, `sleepSettles` in the feedback ledger. Tests: `test_inbox_tend.py`, `SettledChecksTests`. Pick up:
  review; run the dry run on the owner's bank (without, then with `--judge`), read the counts per kind and decision,
  then `POST /inbox/tidy?dryRun=false&judge=true` once and read "Settled by Sleep".
- **2026-10-16 — server and readers: the owner's decisions after headless QA and the hunts (G181, ruling 4b; branch
  `feat/server-readers`, not merged).** Ruling 4b (above): scheduled runs may use the person's plan — Claude or
  ChatGPT — behind an off-by-default switch (Settings → Sleep, `cicada sleep schedule --use-plan`), and
  `cicada engine connect claude-plan|chatgpt-plan` signs a plan in on a server through its own CLI. A schedule with no
  engine it may use warns (schedule, `engine list`, `ask`), plan first. `/healthz` without a token says only status,
  version and bank ids. A client install makes no memory folder. Bookmarks keep what was synced per memory and catch up
  on a bank switch (never the demo); the app's outbox flushes lane by lane, so another memory's refused post never
  blocks the active one's. From the backend hunt: raw watch instants per day (merge order never matters), agent writes
  commit someone else's uncommitted edit apart, long path ids are 404, the session and Messages-photo bodies are bounded
  before parsing, one stuck spool session never blocks turns, Watch later duplicates save `url_index`, a timed-out tool
  write says it may have written; from headless QA: duplicate device names warn, the doctor hint names `doctor.sh`
  where there is no `make`, `sleep status` names the running stage once. Tests: `test_server_readers.py`,
  `test_headless_server.py`, `ServerReadersTests.swift`. Pick up: review and merge; on the home server run
  `cicada engine connect claude-plan`, `cicada sleep engine --mode agent`, `cicada sleep schedule --use-plan on`.
- **2026-10-16 — people from LinkedIn connections: the export enriches who is already in memory, and a skill for the
  rest (G154's pattern, G71, G166; branch `feat/linkedin-people`, not merged).** Owner: "extracting people profiles from
  my LinkedIn connections (maybe could be a skill) would be nice". `linkedin_people.py` reads `Connections.csv` (or the
  export zip; notes preamble, credentials after a comma, the email column never read) behind
  `POST /sources/linkedin-connections/preview|import` (demo 409, admitted, one `user` commit); exactly one existing
  `person` page per connection — never a new page — gains the profile link as a source and dated `external:linkedin`
  `works-at`/`role`/`connected-on` claims, newest wins; removal respected; re-import a no-op. The directory waits at
  `$CICADA_HOME/people/<bank>/` and Sleep's tail (`_rematch_linkedin_safely`, own `cicada` commit) matches later pages.
  Skill `skills/linkedin-people` (own bundle) + stdio-only `cicada_record_profile` (the one listed link, reading on,
  ≤ 10/day, episode with `page` spans). App: the LinkedIn tile's **Connections** (`LinkedInConnectionsPanel`).
  Tests: `test_linkedin_people.py`, `LinkedInConnectionsTests`. Pick up: review and merge; the owner drops his
  Connections.csv in the tile, reads the preview counts, and asks an agent "what does <a known person> do now?".
  **Amendment (owner, 2026-10-17) — the photo:** a person page matched from the connections may use that profile link
  for its photo right away, without the person taking the source — "If it's because I'm connected, unless the agent
  says 'Oh I'm not sure,' then we don't." The link records how it matched (`match`): the page's own name or a link the
  person or an identified agent already listed as their account is confident and drives the photo rung at once (the proxy gate's rules unchanged,
  off by default); an alias-only match is not sure and waits for the person to take it; an ambiguous one writes
  nothing, as before (`linkedin_people.CONFIDENT_MATCHES`, `person_photo.is_own_account`).
- **2026-10-16 — Messages follow-ups: a chat's shared photo is its page's picture, and a mark always reaches Sleep
  (G179; branch `fix/messages-followups`, not merged).** The app reads each ticked chat's shared Messages photo (at most
  hourly, from a copy) and posts changes to `PUT /sources/messages/photos` (409 unticked or demo, 422 bad bytes);
  `messages_photos` keeps them at `$CICADA_HOME/pictures/<bank>/messages/` by conversation, never in a bank or git, and
  links each to its page at read time through the correspondent record; untick deletes it. New rung 2a on both
  resolvers (choice → Contacts → shared Messages photo → profile/logo → monogram), `person` and `tool` pages; it rides
  the `photos` sync component. `messages_source._stage` records the `correspondent`/title on a sitting the stager
  skipped (frontmatter only via `episode_staging.reattribute`, no re-queue of a read sitting). Tests:
  `test_messages_photos.py`, the reproduction in `test_messages_source.py`, Swift watcher and resolver twins. Pick up:
  merge; the owner ticks the agent's chat and checks its page shows the photo.
- **2026-10-16 — on a plan, a run says how much of the plan it used, not dollars (ruling 12's two homes; branch
  `feat/plan-usage-share`, not merged).** Owner: "For Claude plans could you see how much usage was used from the plan
  instead of money?" The backend derives `planShare` per window at read (`cycle_usage.plan_share`): measured when the
  window's reading moved, "under 1%" when it did not (never 0 %), estimated from the run's list-price size against the
  rate earlier cycles moved that window (≥ 2 points each, ≥ 2 cycles, 35 days machine-wide), always with its basis; no
  new ledger field. The app leads Past reads' rows, Last cycle, an opened run and the engine menu's last line with it;
  the dollar figure becomes "would have cost about $X on an API key" (a secondary line or the help). Metered runs keep
  dollars. Tests: `test_plan_share.py`, `PlanShareTextTests`. Pick up: review; the owner's next plan run should read
  "under 1% of your weekly limit · reading unchanged" (or an estimate once two earlier runs moved the window). Not done: Past
  nights' folded run row (no whole-run usage on the history wire; its opened detail shows the share).
- **2026-10-16 — install anywhere: one curl line on Linux, a Homebrew tap in this repo (G181, G76; branch
  `feat/install-anywhere`, not merged).** Owner: "how I can install it with a `curl` command on a Linux machine … can I
  use Brew for that? If not make it so". `scripts/install-server.sh` (curl | bash: prerequisites named together, the
  newest `vX.Y.Z` tag or `CICADA_REF`, `~/.local/share/cicada`, then the checkout's own `install.sh --cli`; re-run is a
  no-op, a new ref restarts the unit, `--uninstall` keeps the memory). `Formula/cicada.rb` (`brew tap rorosaga/cicada
  https://github.com/rorosaga/cicada`; backend + CLI + MCP in a venv on `python@3.12`; `cicada-setup` = `install.sh`
  on the opt path; no `service do`, no cask until notarization). Both build the venv with `scripts/sync-server-env.sh`
  (the lock minus sentence-transformers' subtree: no torch/CUDA; 338 MB on Linux arm64). The formula's tag is a
  version stamp (`check_version.py`, `release.sh bump`). Proven in Docker: `scripts/dev/test-install-linux.sh`
  (ubuntu 24.04 + fedora 41, real systemd) and `scripts/dev/test-install-brew.sh` (Linuxbrew: style, audit --new
  --strict, install, test, setup, upgrade, uninstall). Live from the next release (main has neither file); testers use
  the `dev` URLs in `headless.md`. Pick up: review; after the release, run the curl line on a real server; the website's
  `install.sh` should hand Linux to `install-server.sh` (RELEASING.md).
- **2026-10-16 — headless server, phase 3: the Mac app as a server's client, and Settings → Devices (G181, branch
  `feat/headless-app`, not merged).** Settings → General → *Where your memory lives* (on Settings → Devices since the settings audit, 2026-10-22): This Mac or a server (address +
  device token, checked before anything is written; `$CICADA_HOME/api_base` + `device_token`, used from the next
  launch, and the hooks/MCP/CLI on the Mac follow the same file). On a server the app starts no backend, keeps its
  caches and reader cursors per connection, queues reader posts in `$CICADA_HOME/spool/app` and flushes them when the
  event stream reconnects, and refuses the demo. Settings → Devices shows where the memory lives (reachable, as of
  when), the person's devices (added, last seen; add/revoke on This Mac). New episodes a device posts record `device`
  (`device_context`), shown as "from <device>" on Saved rows, the Reader and the entity card's conversations. Tests:
  `test_headless_app.py`, `HeadlessAppTests` (incl. two real loopback listeners). Pick up: review; the owner tries
  A server against a test server over his overlay.
- **2026-10-16 — headless server, phase 2: every client can talk to a backend on another machine (G181, branch
  `feat/headless-clients`, not merged; ruling 28).** `CICADA_API_BASE` (+ a device token) makes the hooks, the stdio
  MCP server and the CLI clients of a server: the Stop hook reads the session locally and posts turns to
  `/capture/session` (spooled under `$CICADA_HOME/spool/capture` while the server is away), every MCP tool runs on the
  server through `POST /tools/call` (the same bodies), the CLI pins the server's bank by name and id. Per-device tokens
  (`cicada device add|list|revoke`, `/devices`, master only); bank ids in `banks.yaml` (`/healthz` `bankIds`,
  `X-Cicada-Bank-Id`). Proven with two real backends on two loopback ports (`test_headless_two_machines.py`). Unset,
  nothing changes. Pick up: phase 3, the app's server setting (Swift).
- **2026-10-16 — YouTube Watch later and watch history (G71 follow-up, G94, G166; branch `feat/youtube-sync`, not
  merged).** Owner: "my watch later videos from youtube and maybe also sync history" (Takeout once plus Chrome's history
  live), then "the agent being able to go to youtube using the browser … like for youtube watch later/history". Three
  doors, one record: Watch later is a save (`url_index`, one identity across Takeout, bookmarks and the agent); history
  is one episode per platform per day (`watch_history`), never Saved. Built: Takeout's `watch-history.html` read as
  history (it was parsed as bookmarks before), **Include watch history** on the drop and the YouTube tile, the app's
  Chrome History reader (a copy, YouTube video pages only, its own switch under Chrome), `POST
  /sources/watch-history/sync`, and `cicada_record_youtube_list` with Reading the web's two YouTube list switches (the
  reading queue offers a due list; `needs_login` pauses a week). Pick up: review; the owner turns the Chrome switch on
  and checks a day's episode; a real Takeout of a non-English account is not recognised by name yet.
- **2026-10-16 — a web lookup settles questions about public things (ruling 27, G61; branch `feat/web-settles`, not
  merged).** `web_settle` (the filter, the pinned query, the one settle/undo writer, `inbox/settled/`), `web_lookup` (the
  Sleep-tail step: plan search on a run the person started, a metered provider's search at its price, the pinned-query
  check, 8 a run, a 30-day memo outside the bank), `cicada_record_check(outcome="settles")` for the person's own agent
  (repo-state questions from a commit, trusted local agents only), `GET /inbox/settled` + `POST
  /inbox/settled/{id}/undo`, the `web_check` ledger kind, and the Inbox's "Settled by a check" list with Undo and Track
  this source. The answer is a citation on its claim only, never a tracked source. Tests: `test_web_settle.py`,
  `SettledChecksTests`. Pick up: review; then a person-started run on a copy of the real bank, reading the settled list
  and the `web_check` counts (ids only) before merging.
- **2026-10-16 — the web lookup reads local context (ruling 27a, G61; branch `fix/web-lookup-context`, not merged).** The
  first real run settled 0 of 8 (all unsure: an ambiguous name, a wrong category word). The prompt now carries
  `web_settle.local_context` (≤ 600 characters: Cicada's description, up to two mention lines, scrubbed, no one's name,
  no path) to pick the right result; the query is the name plus at most one category word from the description (none on
  a type question); clarifications first, conflicts with a mention line next. `api/scripts/web_check_dry_run.py --bank
  <path> --limit N [--include-recent]` runs the real engine and prints counts only, writing nothing. Pick up: the
  coordinator runs the dry run on the owner's bank (with `--include-recent` to re-measure the first eight) before
  merging.
- **2026-10-16 — the Sleep page redesigned, the Feed folded into it (branch `feat/sleep-redesign`, not merged; owner
  approval 2026-10-16, ⌘ map A).** The "Sleep Cycle" title is gone (an eyebrow: "Sleep · 42 waiting · last read 2 h
  ago"); the room left its card and draws at a whole 5/4/3 pt per cell by the column's width; Details became the tabs
  Waiting · Saved · Videos · Past reads, sticky once the room scrolls away. The Feed page retired: Saved and Videos are
  its list, View menu (sort, kind), detail column, watch run and ⌘N; Connected lives on Sources, export waits head Saved.
  Skills took the Feed's ⌘4 (nothing else moved), with a one-time hint the first time ⌘4 lands there. Ruling 12's
  surface is renamed "the Sleep page's Past reads run detail". DESIGN_RULES §9 carries the dated ruling. Pick up:
  review on the owner's Mac (the worker never launches the app); phase 2 (Clusters into Graph, then ⌘ map B) is not
  part of this branch.

- **2026-10-16 — the key defaults and the price table (G122, branch `fix/byok-default`, not merged).**
  `test_byok_providers` failed on dev because `import litellm` fetched its price table from GitHub at every start
  (ungated), and upstream had dropped the OpenRouter default's alias (today it lists no `openrouter/` row at all). Now
  `api/__init__.py` pins the table to the one litellm ships (`LITELLM_LOCAL_MODEL_COST_MAP`, a control key for the CLI and
  the settings file); defaults moved to listed, priced models with structured output — OpenRouter
  `openrouter/openai/gpt-oss-120b`, xAI `xai/grok-4-1-fast-reasoning-latest`; a saved pref keeping an old id still runs,
  with its cost unknown. The Usage aggregates now say `null`, never `0.0`, for a bucket no call priced.
- **2026-10-15 — Messages conversations, Instinct first, on branch `feat/imessage-instinct` (not merged; G179, G188's
  minimal slice).** Settings → Integrations → Messages: tick a one-to-one conversation, mark who it is with (detector
  registry, Instinct first; the person's mark wins). The app reads only ticked rows past a ROWID cursor; the backend
  decodes `attributedBody`, stages one episode per 3 h sitting, keeps a texted agent's words as `assistant:` turns and
  their claims as `external:<name>`. Bubbles on the Sleep page's What's waiting and Home. Pick up: the coordinator
  ticks the real conversation on the owner's Mac and runs consolidation.
- **2026-10-16 — a texted agent gets its own page (G179, branch `fix/agent-identity`, not merged).** The real run put
  the agent on an archived same-name `concept` page (Stage 2 resolved it by name). Now the episode's decided
  `correspondent` is marked in Stage 1, typed (`tool` agent / `person`) and resolved to its own page in Stage 2
  (`correspondents`; a new page is `<id>-agent` / `<id>-person`), its own claims pinned there; below the unchanged
  promotion bar it is held under that key in the pending store, never on the same-name page. Repair:
  `api.scripts.repair_correspondent_pages --bank <path>` (dry run counts; `--apply` one `cicada` commit) takes a
  conversation's part off a page that absorbed it, moving nothing else. Pick up: review, then the coordinator runs the repair on
  the real bank.
- **2026-10-14 (night) — tracked sources re-checked, on branch `feat/source-refresh` (not merged; ruling 26).** A
  trusted source is re-checked monthly (or on the person's ask) and what it says now is a new dated fact; the newest
  evidence wins, even over the person's words; same-day/undated asks once; two failed visits a week apart mark it dead.
  Public pages: the Sleep tail (`source_refresh.run_tail`, connector gate). Login-walled: only the person's agent
  (`cicada_refresh_claim` / `cicada_record_refresh`, stdio). `GET /sources/due`, `POST /entities/{id}/sources/refresh`,
  the SessionStart line. Not built: the app's rendering of `updates` / due state (the API serves them).
- **2026-10-14 (late evening) — exploring, slice 2, merged as #286.** Depth follows the
  person's reason (G191 ids, their words, their conversations) through a deterministic plan (`explore_plan`; no model),
  a site map per explored site in the bank (`captures/_sites/<site>.md`, append-only, `cicada_site_map`,
  `GET /explore/sites`), and auto-Looks for a design reason (G166, G196). The catalog pins `site-explore` to the dev
  squash commit of #286 (`2a9b5990`; `scripts/verify-skills.sh` passes), as #283 did.
- **2026-10-14 (evening) — exploring saved sites, slice 1, on branch `feat/explore-sites` (not merged).** The owner
  ruled D1–D6 (ruling 25). Built: the explore queue, dated captures with thumbnails in the bank and full images in
  `~/.cicada/captures/`, four stdio MCP tools (`cicada_explore_claim`, `cicada_record_capture`, `cicada_explore_queue`,
  `cicada_explore_start`), `/explore/*` routes, the pinned `skills/site-explore` capture script, the Sources sheet and run
  card, the signed-in switch and Never explore in Settings. The catalog pins `site-explore` to its dev squash commit
  (#283; `scripts/verify-skills.sh` passes). Slices 2 and 3 are open on G166.
- **2026-10-14 (acting-owner session, afternoon) — pick up here.** Merged to dev after the overnight entry below:
  - **#273:** docs for the overnight state.
  - **#274, every agent:** a paste-able setup prompt for Cursor and for "another agent" (G76); Cursor and Gemini CLI conversations are captured through their prompt/reply hooks, built from the documented payloads and not yet seen in the real apps (G197, with a capture matrix in `capture-and-sleep.md`); the owner's ruling on file search (G195).
  - **This PR, agents as contributors:**
    - trusted agents edit a page's text and aliases directly, with blame from git (G198);
    - an untrusted agent's edit becomes a one-tap inbox proposal;
    - inbox questions come up only when the conversation is about them, and an answer the person already gave is relayed with attribution (G115);
    - `cicada_ask` reads a hub page's aliases, summary and linked people.
  - **Found:** an MCP server process started before an update keeps running old code. One refused an owner-page write after the claims-ledger change; it refused safely, without corrupting the page. Opening a new session fixes it. A server that notices a code change and restarts is not built yet.
  - **Owner, open:**
    - whether to turn on the SessionStart/UserPromptSubmit recall hooks in Claude Code and Codex (only the Stop capture hook is installed);
    - which agents go on the page-edit trust list;
    - Cursor capture is the owner's click (Agents → Cursor).
- **2026-10-14 (acting-owner session, overnight) — previous state.** Merged to dev, in three themed PRs per the owner's "fewer, bigger contributions":
  - **#270 memory quality:** a very large page's older claims go to a claims ledger beside it; unnamed people get relation titles and a "What's the name of your partner?" question; `works-at` holds several places at once and ends only on evidence; a project name typed in another case finds its page.
  - **#271:** "Where this comes from" on every page (G61), and the Looks board (G196).
  - **#272:** merges and renames keep every edge whole (a placeholder merge on the real bank had stripped 14,298 claim-backed edges; reverted the same night, nothing lost); hub Related at most 60 lines by meaning; the owner card opens in ~0.1 s; session titles in the person's words.
  - **Owner bank:** the hub split, the works-at reopen (4 places), the placeholder repair (1 merged, 5 asked), an article for the owner page and the episode retitle are all applied, each as its own revertible bank commit.
  - **Tested end to end:** Claude Desktop connects and reads, writes and consolidates, but does not capture its chats (G197). A fresh Claude Code session resumed the project unprompted. The Cursor install dialog awaits the owner's click.
  - **Owner decisions:** G195 (5 questions), G196 (spec questions), G159/G154 Gravatar for contacts.
  - **No Codex** from 2026-10-14: the subscription has ended.
- **2026-10-13 (acting-owner session) — previous state.** Merged to dev: #261 links, videos and PDFs get their own picture (G159 rung 5, PDF page 1 in the backend); #262 platform data exports bring in what the person saved (G71: Instagram, TikTok, YouTube Takeout, LinkedIn, X archive, Reddit; one reader, three doors); #263 pages as articles and #264 one bad answer never aborts the rebuild (G194); #265 a person's photo from their public profile (G159; the ToS rail's one dated exception); #266 the CLI does what the app does (G180, ruling 21a); #267 the backend reads `api/.env` on purpose and `/status` shows what is in effect (it already did, through litellm's import-time dotenv walk — a `python -c` probe cannot see that); #268 age counts from when it was said (G170 amended). Owner bank: 1,050 pages rebuilt as articles (record lossless), then the age recompute — 570 active, 821 faded, 2,241 archived, one question. Rulings: 24 below. Open: Contacts email hash for Gravatar (DECIDE, G154/G159); the X and Pinterest connectors store the post's own text as the person's note (bug, parked); `test_byok_providers` fails on dev (a default model id unknown to the installed litellm); the web-readiness follow-ups listed on G180; the owner page has no article (over the writer's input budget); 222 aliases equal to another page's name; G118 1b; G148.
- **2026-10-09 (acting-owner session) — previous state.** Merged to dev: #249 a recorded alias brings its page to the Stage 2 judge (context, never a decision); #250 the Sleep page answers during a run (G163); #251/#252 skill pages carry their conversations, a skill needs two (G112, ruling 23); #253 EmbeddingGemma 2 is the search model where it runs, #255 its pin file ships; #254 the entity card opens on its wiki page (dated DESIGN_RULES ruling); #256 page quality (G194: promotion measured on the transcript, pending lines keep facts, only an equal fact folds); #257 long embeds run in a child process (coremltools' predict holds the GIL — capture POSTs timed out during a re-embed); #258 Stage 3's page calls overlap; #259 a fresh-process recall reads only what moved (2.15 s → 0.42 s, synthetic). The owner bank was re-embedded with EmbeddingGemma 2 (391 s) and repaired by `repair_page_quality --apply` (544 pages, lossless, checked on a clone first). Engine: Claude plan, Haiku 5.5 for extraction and disambiguation, `CICADA_AGENT_MAX_CONCURRENCY=10`, `CICADA_SLEEP_RESOLVE_CONCURRENCY=10`; summary synthesis on (ruling 23). Superseded 2026-10-13 by ruling 24's age rule: 222 aliases equal to another page's name (merge candidates); G118 1b; G148 Haiku-vs-Sonnet and real-bank embedding comparison.
- **2026-10-08 (acting-owner session) — pick up here.** Merged to dev since the 2026-10-07 entry: #223 docs, #224 engine-timeout pauses (G163/G171), #225/#229/#232/#234/#237 G110 slice 1b (index privacy, light pointer + on-demand context, 16k first message + reply head/tail + `State:` guidance, worktree/subfolder project identity, Cursor startup), #226/#239 dev auto-updater waits out Sleep, #227 no claims fence in any page-body prompt, #228 G169 self-references are the owner, #230 G194 dated writing + *last mentioned* header, #231/#235/#238 G180 CLI slice 1 (eight commands, Settings install, skill), #233 Claude-engine environment never becomes memory, #236 G118 section-provenance records. **Approved, waiting to merge after the clean run:** G118 slice 1b (app *Supporting passages*). **The owner's clean consolidation** is running on a fresh bank of his ChatGPT + Claude exports (1,519 conversations; ChatGPT plan · GPT Luna; batch 25; continue-after-reset off; user-started). The trial bank was stopped and is throwaway; the recovery/reopen work for its lost claims was dropped (owner: old banks are test runs). **Owner direction 2026-10-07:** less review process — one cross-vendor review per change, blockers only; priority is a working memory he can test. **Next:** when the run ends — a quick page-quality pass, merge G118 1b, the owner's live tests (real questions; G110 acceptance: a fresh Claude Code/Codex/Cursor session asked "what was the last thing we were working on?"), then the VERIFY rows. **Open owner decisions:** real-cost measurement vs the input-size proxy for the 16k first-message retention before a release; G118 1a-ii (💸 prompt change + pilot); G179 FDA.
- **2026-10-07 (later, acting-owner session).** Merged to dev since the handoff below: #213 write admission (G183/G177), #214 G98 fold dedup/migration, #215 a prose rewrite never drops a page's claims, #216 closed claims are history on every read path, #217 recovery of dropped claims as closed history (dry run first), #218 G191, #219 G110 rulings A/B/C, #220 rail corner variant A, #221 G192/G193, #222 G148 benchmark harness. In review or build: engine-timeout pauses (a timeout or an unnamed engine-wide failure pauses instead of ending the run or parking the queue; approved, gating), reopen mode for recovered claims (fail-closed admission, round 3), the contradiction-prompt claims fence (G148 follow-up), G180 CLI plan (owner rulings in ruling 21), G110 slice 1b cross-harness plan (owner rulings in ruling 22; revision 2), and a qmd research comparison (two independent reports). The G10 trial drain continues on `trial-2026-10-06` (batch 12 of 89 at writing); external backend restarts pause it and it is resumed at batch boundaries. Owner kept the G105 capture rule when offered tool-call capture; the idea is parked on G112 for research. New trial findings: the owner appears as both a generic `user` page and a named page (owner-entity resolution, G98-class); clean batches of 10 take ~5–10 min (~10 model calls per conversation), and each external backend restart loses the batch in progress (cause under investigation).
- **2026-10-07 handoff (acting-owner session).** Merged to dev: #198 backlog review + ruling 19, #199 G189(a), #200 G185, #201 G183(b,c), #202 G182 release-on-merge, #204 G183(a,e)/G21 guards, #205 installer UTF-8 hotfix, #206 0.3.1 bump, #208 Home scroll + rail corner, #209 G177/G183(d) bank pin, #210 G110 slice 1a, #211 G98 slug-fold core. Releases **v0.3.0** and **v0.3.1** are published from `main`; install acceptance passes on v0.3.1. Backend suite is fully green (G185 fixed). In review: write-admission lock (G183/G177), G98 fold dedup/migration, G148 system-bench runner (found and fixed a Stage-5 claim-loss bug — under opus review), cicada-website #18 (live download button).
- **G10 trial in progress** on a new named bank (`trial-2026-10-06`, ChatGPT plan, gpt-6-luna, user-started drain, batch 10, continue-after-reset off): 1,519 episodes imported via the app (ChatGPT 1,116 + Claude 345 + 5 project notes + 53 memories; count gaps = empty conversations). Findings so far (generic): onboarding has no import step and the import card offers only "read everything"; Claude memory titles show raw paths; the file picker imports a whole folder when nothing is selected; an `api/.env` model pin overrode the engine menu's model for one stage (owner's local config corrected; the mismatch is a product bug); imported episodes swept into Sleep's first commit (G183); the predicate-fold inbox flood (G98, core fixed).
- **Pending owner decisions:** G179 FDA; G110 slice 1b's remaining DECIDE items (after revision 2); reopen counts on a non-trial bank before any write there; GitHub settings for `main` (required Release PR check, PR-only).


- Reviewed merged `dev` at `02979949`; during the review it advanced to `3efba432` with the inbox count fix (#196). This was a code-path/scope audit of 186 original G addresses; subsequent requirements at `ba7a4957` add G188 and amend provider/source/benchmark/release priorities. No live-memory run or full-suite rerun is claimed. Preserve other staged/unstaged work in the shared checkout.
- Import/delta capture, Stop hooks, implicit recall, claims/provenance, Sleep drain, lexical/vector recall, remote MCP, onboarding and release/update infrastructure exist. Completion of the first public release and real-client acceptance are separate open tasks.
- GitHub release listing returned no releases on 2026-10-06. G182’s **built** status must not be read as **published**. Follow [RELEASING.md](../RELEASING.md) for the current mechanism; G182 now requests release-scoped automatic promotion/synchronization as an explicit owner amendment when implemented; implementation PRs target `dev`.
- The [October 5 audit status](audit-2026-10-05/STATUS.md) reports 6,016 backend passes, one G185 usage-join failure and one skip on `4264e297`; Swift 2,957 passes and graph 9/9. These are dated reported results, not checks rerun here. The earlier eight calendar failures are not the current baseline.
- Served-inbox counting code/tests merged during this review as #196 (`3efba432`). Read-side subject/defer filtering and visible-count parity are implemented. G98 retains upstream question-generation/entity-resolution cleanup; it does not ask for the count fix again.
- G169–G172 and G149 implementations are in current merged code. Historical “PR open/not merged” labels in their detailed reasoning are stale. Their live acceptance belongs in the first trial or a named subsequent check.
- No private bank/transcript was inspected; no consolidation, release, upload or skill installation was performed.

## Execution order

| Order | Outcome | Permanent work IDs | Completion condition |
|---|---|---|---|
| Today · urgent | Working GitHub release, main/website sync and every integration | G182/G76/G10; website G158 | Due 2026-10-06: real downloadable artifact, fresh install/update acceptance, released tag/version/manifest/main synchronized by an explicit release workflow, working website link. Test every catalog harness and supported desktop/web/mobile route after actual consolidation for grounded reads and attributed contributions; blocked/unsupported is explicit. Later add tested CLI/server install commands and harness access guides when G180/G181/G187 ship. [Requirements](../specs/2026-10-06-release-and-integration-acceptance.md). Applicable integrity checks remain release dependencies. |
| Today · quick | Painted Home banner off | G189 (a) | One `HomeBandLayout.showsBand = false` gate around `HomeHeroBand()`; existing Home/scene tests keep passing; dated DESIGN_RULES ruling and the app.md Home paragraph in the same PR; checked by eye in the running app, light and dark. |
| 1 · P0 | Protect current truth and commits | G183/G177; G104; G21 if live dedup is used | Repair applicable page-lock, owned-path, author and bank-switch defects. Reproduce revised-source retention with synthetic episodes, then fix the demonstrated semantic gap before a full re-consolidation. Dedup must commit its own merges. App controls must use the writing window. |
| 2 · P0 | Reproduce the known regression | G185 | Diagnose and fix the reported usage-join assertion without weakening it. Release gate; consolidation gate only if it exposes drain correctness. |
| 3 · P1 | First useful memory, including actual source/video cases | G10, G169–G172; G61/G166, G22/G162 | Small fresh/delta ChatGPT/Claude export trial first. Ask ordinary dated/current questions, correct a claim and repeat in a fresh session. Then demonstrate permitted source lookup/recording and an actual watched-video → Sleep → grounded recall. Build the missing general source-check seam; separate watch success from processing/answer quality. |
| 3b · P1 | Automatic continuity when a session is full or the agent changes | G110/G48/G53/G75/G76/G149; Cursor G50; remote G135 | Fresh Claude Code/Codex session continues the active project before Sleep without a handoff prompt or recap. Then prove Claude Code → Cursor/Codex and permitted Grok/remote continuation. Recover goal, decisions, current changes, verified results, blockers and next step; detect stale workspace/ambiguous tasks, preserve lineage and disclose unavailable context. See [required behavior](../specs/2026-10-06-project-continuity.md). |
| 3c · P1 research | Efficient continuation-aware consolidation | G104 with G110/G118/G163 | Compare full-thread rereads with new turns plus bounded prior context, stable unit reuse and targeted reprocessing. Measure repeated input/calls/time and useful recall; preserve corrections, evidence and commit-safe checkpoints. Investigate capture-cap loss. [Research brief](../research/2026-10-06-incremental-consolidation.md). Existing revision correctness stays P0; optimization does not gate the small baseline trial. |
| 3d · P1 | Rebuild whole-system benchmarks from scratch | G148; G10/G104/G171/G183 | New isolated subscription-capable harness: intake → real five-stage Sleep/tail/owned commits/indexes → held-out answers, continued/revised sources, temporal changes, failure/resume and scale. Measure quality/integrity plus runtime, throughput, CPU/peak memory, calls/reported tokens and service latency. Synthetic cases then one LoCoMo conversation/30 questions; Luna pin for every generative stage. Legacy scores are not acceptance evidence. [Requirements](../specs/2026-10-06-system-benchmark-rebuild.md). Full harness does not gate a small hands-on trial. |
| 4 · P1 | Repair the failures that make answers untrustworthy | G98/G118/G147/G103; G93/G53/G113/G115/G141 as indicated | Canonical/retired question subjects, preserved keep feedback on merge, intelligible observer and evidence navigation. Trigger/rationale trace slices and cross-stream relevance follow observed trial failures. Do not rebuild already-implemented state/Ask/Reader components. |
| 4b · P1 | Selected iMessage conversations, optional Instinct recognition | G179; minimum G188 seam; G95/G134 attribution | App reads selected permitted bytes; backend parses scrubbed attributed drafts. Verify continuation/revision/deletion/date/source semantics through actual Sleep and useful answers. Optional separate Instinct detector supports uncertainty/user overrides and never broadens capture. [Requirements](../specs/2026-10-06-provider-and-ingestion-modularity.md). Other messenger exports follow later. |
| 5 · P2 | Shell agents use a lean governed surface | G180; G157 redirects | Packaged CLI, structured output/error/discovery contracts and portable usage skill; measure schema/task overhead. Keep scoped MCP for clients without a shell. |
| 6 · P2 | App-free server package | G181/G187/G135/G92; Cursor engine G50/G49/G122 | Supported Linux/macOS install/service/upgrade path with one primary bank writer and client/remote smoke checks. Evaluate Windows native versus WSL separately. An existing Python backend is not a supported headless package. **2026-10-15:** phase 1 (Linux install + systemd user unit, commits with no git identity) on `feat/headless-server`; the plan and the owner decisions for phase 2 are in G181 and `docs/research/2026-10-15-headless-server.md`. **2026-10-16:** the packages — one curl line on Linux (`scripts/install-server.sh`) and a Homebrew tap in this repo (`Formula/cicada.rb`), both proven end to end in Docker (`feat/install-anywhere`). |
| 7 · P2 | Modular providers and ingestion in frontend/backend | G50/G49/G122; G188/G190/G126/G161; Cursor G76/G110 | Registered capabilities/small adapters drive setup/status/engine controls and source intake. Add/remove a fixture provider/source without unrelated core/view changes; preserve unavailable saved selections/history. Verify Cursor client versus engine capabilities separately. iMessage uses a minimal source/detector seam earlier; broader migration follows. [Requirements](../specs/2026-10-06-provider-and-ingestion-modularity.md). |
| 8 · P2 | Start prompts and portable skills | G73/G118/G113, G138/G178, G112/G55; G186 after CLI | Save/find/adapt reusable objective briefs with candidate status, original/variant provenance, project inputs and outcome evidence; copy/export across harnesses without requiring Sleep or skill compilation. See [start prompts](../specs/2026-10-06-start-prompts.md). Then verify catalog/BYO install, ground existing skills and compile standalone bundles; demonstrate schema-aware SQL reuse with R2 governance. Generate AMR export separately; external AMR import remains research. |
| 8b · P2 | Home revamp | G189 (b); G110/G137/G125 | **2026-10-14:** owner picked "Graduate + Needs you first" (built on `feat/home-front-door`; retake Home's screenshots on the demo bank, light/dark, first-week/returning/empty). Still open: projects in flight and what changed since the last visit, from 2–3 direction-D mockups. Do not rebuild the Ask field or inbox counts. |
| 9 · P3 | Design identity and personal mascot | G70/G151, G127, G175/G176; G73 supplies creation templates | Start with own-repo/image tokens, cited structured design read/UI, then vision/video/style bundles. Add Cicada skin, copyable neutral creation prompt and validated sprite import/preview. Remaining app/Reader work follows the explicit ledger; profile G184 before energy changes. |
| 10 · P4 | Multi-server/device sync and selective contributors | G132/G1/G181, G16/G103/G116/G92 | Many clients of one writer first; backup separate from replication. Specify node/project scopes, contributor routing, evidence exposure, revocation and conflict verdicts before offline replication or multi-person writes. |
| Triggered only | Additional channels and model/browser research | Later/Research IDs; G167/G168 | Dedicated adapters are not implemented by generic ingestion. Work from a named use case/failure/trigger; keep declined parallel reading and relational-tier decisions out of the automatic build queue. |

**How to use this order:** a small trial does not wait for every P1 enhancement. Correctness fixes relevant to its writes come first; a full drain must wait on demonstrated revision/commit defects. G104’s incremental strategy is P1 research rather than a prerequisite performance rewrite; its P0 correctness slice remains separate. Alongside today’s explicit release deadline, automatic session/project continuity and source/video quality remain P1 because the owner wants useful conversations. Cursor’s provider adapter is an explicit P2 integration remainder under G50; its capture/startup behavior supports P1 G110. G182 is the owner’s explicit delivery priority for today, with applicable release checks. G148 whole-system benchmark replacement and selected iMessage/Instinct capture are P1; full harness completion and an embedding upgrade do not gate a small hands-on trial. Broader provider/source modularity and CLI/headless packaging are P2. The [187-ID review](BACKLOG_IMPLEMENTATION_REVIEW.md) spells out implementation versus missing slices. Older “built” labels apply only to the named slice; G1/G23 were restored from DONE.

## Client trial matrix — support must be demonstrated

| Client | Trial path | What to establish |
|---|---|---|
| Claude Code | Existing local MCP/Stop/recall hooks; CLI once built | Automatic capture, fresh-session retrieval, provenance, correction and reusable procedure. |
| Codex | Existing local MCP/Stop/recall hooks; CLI once built | Same behavior, with session/model attribution limits disclosed. |
| Cursor | Existing agent catalog/MCP setup; complete G50/G76 capture/recall and supported engine integration | Fresh-session and cross-agent project continuation without a handoff prompt; verify actual capture, model/session attribution and available engine functions. |
| Grok | Scoped G135 connector with selected project/task | Automatically recover permitted working context on a new conversation where supported; disclose missing workspace/source access. |
| ChatGPT Desktop | Check current supported remote-connector setup via G135 | Read/write/source scopes and continuity if supported; connection does not establish automatic capture. |
| Claude Desktop | Local MCP registration or supported remote connector | Recall and attributed contributions; no Stop-hook capture claim for this app. |
| Claude web (claude.ai) | Supported remote MCP route via G135 | Post-Sleep grounded recall and attributed contribution; source scopes and current account availability. |
| ChatGPT web | Supported remote connector via G135 | Same post-Sleep read/contribute check; distinguish connector availability from automatic capture. |
| OpenCode | Catalog setup prompt; verify current supported MCP/config path | Fresh-session grounded recall, attributed contribution and persistence; capture/continuity checked separately. |
| Hermes | Catalog setup prompt; verify current supported MCP/config path | Same read/contribute/persistence check; report actual supported setup and capture limits. |
| OpenClaw | Catalog setup prompt; verify current supported MCP/config path | Same read/contribute/persistence check, including source scopes and active-bank isolation. |
| Gemini CLI | Existing catalog/setup path | Same read/contribute/persistence check; verify attribution and automatic capture/recall support separately. |
| iPhone AI apps | Verify current connector availability per app/account | Test an authenticated remote connection only where supported; otherwise record unavailable plus export/manual capture fallback. |

For **every row**, use a fresh session after actual consolidation: recall and correctly use a synthetic memory, write a permitted attributed contribution, retrieve it from another fresh session/client, and verify its persistence/evidence/commit. Record read, contribution, source scope, capture and continuity separately. Enumerate each tested iPhone app rather than claiming one mobile check covers all apps. Record availability/date and PASS/FAIL/BLOCKED/UNSUPPORTED plus the exact supported setup, build/account/platform and generic evidence; registration or connection is not a pass. No personal question text or retrieved private facts belongs here. [Full protocol](../specs/2026-10-06-release-and-integration-acceptance.md).

## Embeddings: EmbeddingGemma 2 where it runs (owner 2026-10-09)

Markdown, evidence and git hold memory. Embeddings provide semantic recall and candidates for entity resolution/dedup; they are not the authoritative record. `search_service.py` fuses lexical, vector and claim results and can fall back when vectors fail. `entity_resolver.py` still reads/writes the pending entity index, so full consolidation is not established as an index-free mode.

**Ruling (owner 2026-10-09, after the spike: "cant we just run everything with embedding gemma 2?").** EmbeddingGemma 2 on the Neural Engine (`google/embeddinggemma-2:768`, Core ML, macOS 15+ on Apple silicon) is the embedder wherever it runs: Sleep's index builds, recall from MCP and the CLI, the release app. It is downloaded once on the person's request (Settings, `make embedding-model-gemma2`, `install.sh`), never bundled; the release keeps `intfloat/multilingual-e5-small` (384) bundled as the floor for macOS 14, a download not finished yet or a failed load, and search never errors. A bank recording one of Cicada's former defaults moves to it in a **background re-embed** that never runs during Sleep and never blocks recall (the old table answers until its replacement commits); a model the person chose or set explicitly is kept. This replaces "keep the present choice for the first trial": the evidence is the spike (parity ≥ 0.9998 with the reference model; cross-language EN↔ES page retrieval +0.11 MRR over e5 on a 3k-page set; a query 2.8 ms) and the build's own measurements (`docs/architecture/storage.md`, sqlite-vec). Revisit only if the owner's real-bank comparison (G148) shows meaning-based recall worse than e5's on literal or paraphrased questions. Check the active bank's actual selection, `reindex` state and index health through `GET /embeddings` at execution time; do not assume it from the build type. If meaning-based recall fails but lexical recall succeeds, record that failure for G148.

## Consolidation boundaries

Use a separate named real test bank or an explicitly chosen existing bank, with a recoverable committed baseline. New exports are imported normally; do not wipe the bank or mark every episode unprocessed to force a rerun. Inspect the import preview, preserve dates/speakers, then run a small batch with the selected engine. An API-funded run needs a budget; a user-started plan engine respects its plan limits and pause behavior. Scheduled plan use needs the person's switch (ruling 4b). Runbook details: [G10 trial](2026-10-06-first-memory-trial.md).

## Unstructured follow-ups retained from the old handoff

These are attached to permanent rows instead of becoming a second queue. Older disclosures require a current-code reproduction before implementation; do not re-open an audit fix from historical prose.

- **G106/G19:** confirm remaining client/backend ID sanitizer parity and wikilink navigation outside a WindowGroup.
- **G109:** graph physics phases/visual fit check; re-check historical WKWebView remount claims against the merged audit fixes.
- **G162 (model check 2026-10-22):** F1, F2, F3 and F5 in the queue's lease lifecycle are open with xfail-strict repros (`api/tests/test_video_queue_formal.py`), each low to negligible likelihood, with proposals checked in the model (a lease token, the saved set read under the lock, `requested_at` to the microsecond); F3 and F4 are the owner's call. Any change to `video_queue.py`, `video_state.py`, the record or claim tools or how a caller gets its session id runs `.claude/skills/verify-video-queue/run.sh`.
- **G162:** `/live/<id>` normalization changes need URL-index migration; unprobed player providers stay unverified; do not assemble third-party widget HTML or bypass an origin restriction. **G11:** verify the disclosed duplicate direct-file preview/hero player.
- **G135/G177/G183:** current remote/local write races and fail-open commit probes; check scope isolation, timeout behavior and source permissions. **G61:** source entry identity, check-date/predicate invalidation and save-time fetch limits against the current common fetch guard.
- **G130/G137/G184:** zoom/sidebar clamp, pixel-size alignment and active-run animation energy. Nightcap/time-of-day absence are superseded by shipped G176 art. DS-3c card Esc and Settings folder popover seams remain current-code checks.
- **G146:** `lastReferenced` in graph shape/hash and Clusters age. **G161/G118:** source item’s saving episode for “Show in conversation.” **G118/G141:** recently learned claims with evidence spans from history, without claim text in commits.
- **G133:** reproduce garbled imported-paper titles with synthetic files. **G103:** humanize raw-predicate fallback. **G76:** distinguish capture enabled from recall connected. **G145/G173:** versioning untouched generated demo data, if the stale-demo trigger persists.
- **G7:** centrality premise remains unproved; no tracked measurement was found, so it is not archived as done.
- **G92/G19:** old bank-history size is historical, not permission to rewrite git history. No destructive cleanup is implied.

## Maintaining this queue

A whole row moves to DONE only after its remaining implementation and required acceptance are complete. If only one slice ships, name the remaining slice and keep the G ID active. Update this file and the reasoning row together; never renumber or silently discard an unresolved seam. Use [working-method.md](working-method.md) for the implementation bar and [BACKLOG_CONTEXT.md](BACKLOG_CONTEXT.md) for original prompts rather than loading old execution logs as current instructions.

## Rulings that cost real work to derive — do not re-litigate without reading them

1. **Decay charges once, and never for an outage.** Decay used to re-subtract the whole elapsed
   interval every run (proven: `octo.md` 0.85 → 0.4714 → 0.0928 in three commits *on one day*).
   Fixed with a `decayed_through` watermark + a per-cycle cap, plus a one-shot migration because
   the first cycle after the 75-day engine outage would have **archived 1,536 of 1,882 pages**.
   The principle: *an engine outage is a system failure, not user silence.* Migration has run;
   first-cycle archive count is now **0**, verified with a negative control.
2. **No relational tier** (G99). Measured, not assumed — three of four "SQL would fix this"
   arguments collapsed. Revisit only on the named triggers in that row.
3. **Markdown+git is the only source of truth.** A `.db` may exist only if deleting it costs CPU
   and never a fact, and **no derived artifact is ever tracked in a bank's git** (the 35 MB index
   was tracked and would have committed ~11 GB/yr once Sleep resumed).
4. **Scheduled cycles cannot spend plan quota — Claude or ChatGPT.** `user_triggered` is threaded
   through; a scheduled cycle returns `byok` before the registry is touched, and a Settings-chosen
   `agent` **or `codex`** is demoted to `byok` on a schedule by one tuple,
   `engine_select.SUBSCRIPTION_MODES`, so a third plan engine cannot forget the guard (Track E,
   2026-09-23). Only an explicit `CICADA_LLM_MODE` in `api/.env` runs a plan on the schedule. The UI
   copy says "never on the nightly schedule" and that is literally true for both plans.
   **4b — amended (owner, 2026-10-16): "The server should be allowed to use plans too. Just have to set them up
   somehow."** and, on the ChatGPT plan, the same day: **"Yeah chat too."** A machine may let **scheduled** runs use
   the person's plan behind an explicit switch, **off by default**: "Scheduled runs may use my plan" in Settings → Sleep,
   `cicada sleep schedule --use-plan on|off`, stored machine-wide as `sleep_run_prefs.scheduled_use_plan`; where it is
   turned on it says once that nightly runs then count against the plan's limits. With it on, a scheduled run resolves
   exactly as one the person starts would — the Claude or the ChatGPT plan, each only when it is the engine the person's
   own choice resolves to and it is signed in (`engine_select.SCHEDULE_PLAN_MODES`). `SUBSCRIPTION_MODES` stays the one
   guard; the switch is its only door besides an explicit `CICADA_LLM_MODE`. Such a run drains like any scheduled run
   (the dotfile pin keeps ruling 16's one batch); a plan limit pauses it, Past reads shows the plan share (#317), and the
   schedule replaces its `plan_window`/`plan_weekly` pause once the limit has reset (the vendor's `resets_at`, else after
   six hours) since on a server nobody presses Continue; extra usage stays the person's and ruling 15's continue never
   arms from a scheduled run. The scheduled web lookup (ruling 27) may use the Claude plan's search under the switch too.
   **Setting a plan up headless:** `cicada engine connect claude-plan` (Claude Code's own `claude auth login
   --claudeai`; where it cannot finish, `claude setup-token` elsewhere and `CLAUDE_CODE_OAUTH_TOKEN` in the unit's own
   environment, which reads as `oauth_token`, a plan) and `cicada engine connect chatgpt-plan` (the Codex CLI's own
   `codex login --device-auth`, in Cicada's own `CODEX_HOME`): in the person's own terminal on the server, through the
   CLI's own sign-in; Cicada never sees, prints or stores the token. **Owner decision 2, same day:** a schedule with no
   engine it may use says so — when it is turned on (`/sleep/schedule`'s `warning`), in `engine list` ("no key"), and
   `ask` says it has no engine — each offering to connect a plan first. Revisit if a scheduled run is found to have
   spent a plan without the switch on, or if the switch's disclosure is found missing where it is turned on.
   **4c — the switch is on by default (owner, 2026-10-19): "Make scheduled runs run on the plan by default."** A machine
   that never set it (a new install, a bank that never chose) reads as ON; only the person's explicit off stops it, and
   an off is now stored as `false` so it outlives the default (`sleep_run_prefs._switch`; a hand-edited non-boolean
   reads as off). Every surface that said "off by default" says so no more (Settings → Sleep's detail line, the CLI,
   the docs). `SUBSCRIPTION_MODES` stays the one guard and the switch its door. An off set before 2026-10-19 was stored
   as an absent key and reads as on now — that state was indistinguishable from never set. Revisit if a person is
   found surprised by a nightly run on their plan they never agreed to, or if the plan share of scheduled runs crowds
   out the runs they start.
5. **Raw storage does not replace Sleep** (G101). Text cannot decay — only a belief can go stale or
   be contradicted — so "time as a signal" needs a belief object.
6. **Capture is agent-judgment and that is a measured problem** (G105): 0 MCP invocations in 12
   days; 4 episodes from one very long session. **Answered by the G105 hook (2026-09-03):** capture
   is now a property of the harness's Stop hook, not of a model's tool call — the MCP
   `cicada_save_episode` path stays as the deliberate, agent-chosen episode.
7. **The Stop hook, not SessionEnd, is the capture trigger** (G105 R1) — SessionEnd never fires for
   a closed window or a killed process and shares a 1.5 s budget; the endpoint's content-hash
   short-circuit makes per-turn firing idempotent. Revisit only if `capture.log` starts showing
   timeout `error:` lines (the hook's 3 s budget, `TIMEOUT_S` in `api/hooks/capture.py`) on the live
   bank — the hook logs no timing, so a blown budget surfaces as an `error:` line, not a latency figure.
8. **The Sleep page shows the ACTIVE stage, and there is one translation** (Track Z R-Z14). The
   wire's `stage` counts completed stages (`sleep_cycle.py` sets 1 only after Stage 1 returns);
   three derivations clamped it without adding one, so the worm, the bracket line and VoiceOver
   said "stage 1" while Sort ran. `activeStage(completed:)` is the only way any view turns the
   wire number into a stage. Revisit only if the backend starts reporting the stage in flight.
9. **Pixel art beside the worm is checked against the real worm, per weather** (Track Z
   Z-P13). A hand-approximated worm passed two window clouds the real frames hide (the head's
   shake uncovers a column); `WindowSpritesTests` masks with every look of every mood that shows
   that weather. Any new art near the worm gets the same test.
10. **The Sleep page's sky band is off** (Track Z Z-B16, spec decision 16). Built behind one
    constant, `SkyBand.ships`; gated in the build by `SkyBandTests` (a band's top composited over
    the page stays within 1.35:1 of it and keeps text ≥ 7:1, both modes, every sky) and decided
    by eye from the day/dusk/night × light/dark composites against a no-band control: every gate
    passed, yet the light-mode night and dusk bands read as a neutral grey haze pressing on the
    title — a smudge, not a sky — the dark night band was invisible and dark day a lighter slate
    strip; only light day read as a tint, and a band that works in one of six cases is not a
    feature. Measured tint / title ratios (: 1): light day 1.04 / 14.8, dusk 1.26 / 12.2, night
    1.29 / 11.9; dark day 1.29 / 12.4, dusk 1.02 / 15.7, night 1.00 / 16.0 — so the gates alone
    cannot decide it. Revisit only with new composites — flip the constant and re-run
    `CICADA_WRITE_COMPOSITES=1 swift test --filter SkyBandTests`.
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
12. **Plan usage and model prices show on the Sleep page's Past reads run detail and its engine menu — and
    nowhere else yet (owner, 2026-09-28; surface renamed 2026-10-16, when the Sleep redesign turned Details into the
    page's tabs: Details' Last cycle and Past nights are the Past reads tab, so the figures live where they lived —
    `PriceLintTests` still holds them to `SleepDetails.swift`, `CycleUsageText` and the engine menu).** This supersedes the 2026-09-03 "prices and token usage are not
    shown anywhere in the app" ruling for those two surfaces only; ruling 4 (a scheduled cycle never
    spends plan quota) is untouched, and so is the no-cost-tiles, no-cost-per-day-chart half of the
    old ruling.

    What is shown, and why it is honest:
    - **Every figure carries its basis in words.** "Charged" is the provider's own bill (API key,
      OpenRouter). "At list price" is an estimate from the public price table or the Claude CLI's
      metering, never a charge. A plan cycle is its window's before → after.
    - **On a plan, the share leads, not dollars (owner, 2026-10-16).** A plan run says how much of each window it
      used — measured (the reading moved), "under 1%" (it did not; never 0 %), or estimated from the run's list-price
      size against earlier cycles' observed rate, each basis said, an estimate never shown as a reading. Its list-price
      figure stays only as the secondary "would have cost about $X on an API key". Metered runs keep dollars.
    - **A plan's percentage is the whole plan's.** The change across a cycle can include anything else
      the person used meanwhile; the UI says so. Claude reports a window only after a call, so its
      "before" is the reading after the cycle's first call, not a pre-cycle one.
    - **Unknown is never zero.** A ChatGPT plan call reports no tokens and no cost, so it reads
      "tokens not reported". A cycle from before this shipped, an aborted or idle one (no `sleep_run`),
      and an inbox or decay commit have no usage; the first three read "Usage not recorded" and the
      commits say nothing.
    - **Only consolidation is counted.** Calls are tagged from the cycle's own scope; the
      engine-independent tail (link backfill and the like) runs outside it and is not in a cycle's cost.
    - **The ledger stays ids, enums and numbers.** `refs.cycle_id` on `llm_call` and a `plan` block
      on `sleep_run`; never text.

    Revisit (widen it beyond the Sleep page) only when the owner asks for a second surface.

13. **Consolidate reads everything — a person-started run drains the whole queue, in batches (owner,
    2026-09-29); a scheduled one reads one batch — amended 2026-09-30 by ruling 16: it reads everything too.** The owner: "i dont want to cap the max episodes per
    sleep, why would we cap them? its just progress that cicada has to go through." This amends **G125
    R10** ("one trigger, one cycle") and **reverses the v5 spec's V5-15 / Q7** (a no-body trigger is one
    batch; a drain only from a sheet): Consolidate *is* the drain, no sheet, no `/sleep/run/continue`.
    Ruling 4 is untouched.

    - **Shape.** `POST /sleep/trigger` runs `run(drain=True)`: freeze the waiting ids, resolve the engine once,
      read them in batches of `sleep_max_episodes_per_cycle` (default 25, now "how often progress is saved"), each
      batch filed and committed by Stage 5, so a cancel or a plan stop loses at most the batch in progress.
    - ~~**Scheduled = one batch.**~~ *Amended 2026-09-30 (ruling 16):* a scheduled run drains the queue too, on the
      scheduled engine (`user_triggered=False`, so never a plan — ruling 4 unchanged). The original reason — an
      unattended run on an API key reading everything is real money — is now said in words in the engine menu and
      Details instead of being prevented.
    - **Once per drain:** decay (both engines; ruling 1 — charged once, not once per batch) and Stage 5.57's page
      reads, in the batch that empties the queue. **Once per run:** the engine-independent tail. Everything else per
      batch, so each commit is self-consistent.
    - **A plan limit is a pause, not a failure,** with the vendor's own sentence and reset time. *Since built
      (2026-09-30, Sleep page v5):* Continue / End this run on a paused record, the opt-in continue-after-reset
      (ruling 15), the "leave room in my plan" reserve, run-level Past nights. **Still not built:** a journal of paid
      answers (a cancel or a hard rejection before Stage 5 still discards the batch in progress), parallel reading
      ("Read faster" — the owner declined it for now, G163).
    - **Cost accepted:** bank switching, export and delete are refused for the whole run (the drain is pinned to its
      bank) — by name, and the app shows the sentence. Every other guard and the MCP write probe follow **G177**'s
      write window (`sleep_cycle.is_writing()`), so an agent's claim between batches commits alone under its own author.

    Revisit only on the trigger G163's row names (the journal slice; the reserve and Continue are built), or if a drain's plan volume
    hurts a real owner's coding budget.

14. **Reading with the person's own agent — Cicada asks, the agent reads, the backend holds no session
    (owner, 2026-09-29: "i want the agent using browser harness … or the native computer/browser harnesses from the
    chatgpt app and claude app, which uses the logged in sessions and swiftly surfaces 'needs login'… I want this built
    now"; G166, spec `2026-09-29-reading-the-web-design.md`).** Four of the spec's proposed rulings are now binding; the
    rest (R-RW1–3 the Reader's identity and metadata tier, R-RW6–7 and R-RW12 chat links, R-RW10–11 robots and backoff)
    stay with the Reader slices.
    - **Amended 2026-09-30 — no pre-picked site list; sites are surfaced from the reader's own failures (owner: "limiting the
      amount of sites makes no sense to me, because we will never know which sites this will happen").** The five per-site
      switches are gone. A saved page Cicada's own reader could not read — a sign-in, a consent wall, a refusal, or a host the
      backend never requests — is a *wall page* (`reading_walls`, from stamps the fetchers already write, and only while it
      holds no words); wall pages group by site (`reading_hosts.site_of`); Settings → Reading the web lists those sites with
      measured counts and a per-site switch, off until the person turns it on (`reading.agent_sites`, a grant refused for a
      site nothing has surfaced). Surfacing follows the reader's failures *wherever they happen* — save time, the in-cycle
      pass, the backfill — so the backfill's throughput never bounds it. The master switch, the versioned acknowledgement
      (now v2, without the site picker) and per-page "Ask an agent" stay. Copy across the branch is provider-neutral: it
      describes the step ("summarized by the engine you chose for Sleep"), and names a provider or model only where it
      shows the person's own current choice. **Amended clauses:** R-RW8's "per link, for a site the person switched on" is
      "per link, or per site the person turned on after a page from it could not be read"; "Reddit and `t.co` are never
      offered; the other five are five per-site switches" is "`t.co` is never offered; Reddit surfaces like any site"; and
      Track P R5 (a retired interstitial or login wall stays out of the Feed) now lets a page through **only** when it is such
      a wall an agent can be asked to read, or an agent already read it. **Review 2026-09-30:** a row an agent's own outcome wrote
      (`origin: site`) is no consent of its own — it authorizes a record only while the site is still allowed and the
      page is still a wall page, so switching a site off revokes recording as it dequeues; a connector whose saved item
      *is* the post (X bookmarks: the text in `## Notes`) holds words, while a Reddit or Pinterest save is a link out
      whose title or pin description is not the linked page, and surfaces on purpose.
    - **A site switch is a standing permission, derived not fanned out (2026-09-30).** The queue is the person's asks plus
      wall pages of allowed sites, computed at read (`reading_queue`): a switch writes one line, a new wall page joins with
      no write, turning it off (or the master) dequeues at once. An agent's `needs_login` pauses that site's derived entries
      until the row expires (7 days), the person asks again on a page, or switches the site on again ("try again"): an agent
      that is not signed in is asked again at most weekly. Pacing is one entry per site per call. Grants are machine-wide
      (`reading.json`); the pause is per bank (the ask store is).
    - **The Feed shows a wall without being opened (review, 2026-09-30).** The row's second line says "Needs sign-in" and a
      toast announces a link that just hit a wall (not on the first look after launch); the text is the text ladder plus a
      neutral glyph, not `warning` (DR-7 is unchanged). A quote from `cicada_record_read` is labelled "From the page, as
      <agent> read it", never bare "From the page" (spec §8.5).
    - **R-RW8 — the ruling that keeps this from eroding the rail.** The standing rail ("no scraping behind
      authentication", 4 s / ≤ 512 KB / no cookies / a block never retried with different headers) governs *Cicada's own
      fetcher* and is unchanged. Agent reading is person-driven and never scheduled; Cicada only *asks* — per link, or per
      site the person turned on after a page from it could not be read, after a versioned first-use acknowledgement — and
      promises nothing about what the
      agent does in its own browser. The backend never holds a session, a cookie or a profile. No Cicada text says
      "read-only" or "never posts"; contract item 9 and the hand-off prompt are *instructions*, not promises.
    - **R-RW4 — one closed set of login-walled hosts, and the backend's page readers never fetch one.** X, Facebook, LinkedIn,
      Instagram, TikTok, Reddit and `t.co` (dot-boundary match: `lnkd.in` and `fb.watch` in, `notx.com` out). This closes
      the X gap (X fell through to the OpenGraph fetch). TikTok keeps its provider oEmbed branch, which never loads the
      page, and the Reddit and X connectors still call their own APIs; the rule covers the *page* fetch of
      `media_ingestor.enrich` and the `link_enrichment` backfill. `t.co` is never offered to an agent. There is no pre-picked list of sites: a site is *surfaced* when Cicada's own
      reader cannot read one of its pages (a sign-in, a consent wall, a refusal, or a host the backend never requests) and
      the person turns it on, per site, on Settings → Reading the web. Site icons come from the icon service only, and a walled
      site is never contacted for its favicon either.
      `link_enrichment._excluded_media` is shared with `fact_sources.is_refused_host` and `link_recon`, so a source on
      such a host now reads as needing the person's login there too.
    - **R-RW5 — a link that carries a secret or a side effect is never offered** (a token-like query key, an
      unsubscribe/verify/reset/logout/oauth path segment, a signed URL, a private-workspace host, a userinfo or non-web
      port), nor is a local or reserved host, an AI vendor's own page, a video (the video path owns it) or a paper.
    - **R-RW9 — `--chrome` is in no argv** (`test_reading_never_spawns_browser.py`). Measured: it overrides
      `--safe-mode`, `--strict-mcp-config` and `--tools ""`.
    - **Only a link the person asked about, or a wall page of a site they allowed, can be recorded (review, 2026-09-29;
      amended 2026-09-30).** `cicada_record_read` refuses every outcome, `read` included, for any other URL, whether or not
      the link is saved (a saved public page with no wall too), and `reading_asks.record_outcome` creates a row only for the
      site case (`origin: site`) — otherwise it writes nothing without a live row. **Exposure, stated:** with a site grant the
      person consented to a *site*, not to a page, so any agent holding `record` can then record a wall page of that site;
      the structural denials (R-RW5), the master switch, ask-store-only outcomes and `page`-kind spans bound it. Before this a saved link with no ask took any outcome
      (a rewritten description, a planted `needs_login`), which is what a page steering an agent would use.
    - **The outcome is stored where it can be shown at once.** `needs_login`, `blocked`, `not_found` and `failed` live
      only in the machine-wide ask store (no bank write, no commit, no Sleep gate) and move the `reading` sync component;
      only a successful `read` is memory. Chosen over writing the page because a page write needs a commit, is refused
      remotely while Sleep runs, and does not exist for a link that was never saved.
    - **An ask's URL is visible to any connection holding `read`** (this departs from the spec's §8.4, which hid a
      `role: user` row's URL without `sources`). Cause: the person's explicit "Ask an agent" *is* the consent to hand that
      one URL to an agent (and, amended 2026-09-30, their grant for a site is the consent for that site's wall pages — a
      site entry from a channel that is the person's own words, such as Telegram, an agent's save or a chat export, needs
      `sources`; only saved-content channels are served to `read`), and the default scopes are search/read/record, so applying the old rule would leave the ChatGPT
      and Claude apps unable to read any ask. `sources` still gates every verbatim word of the person's conversations, an
      inbox `Cause:` quote and any chat-harvested URL (not built yet). No `why` or note text is served remotely.
    - **How the agent reads is a selection, and an instruction (2026-09-30; owner: "i want to use the macos-harness, the
      browser-harness and claude-video … as selections in settings, amongst the other default options models can use through
      their harnesses").** "Let my agent choose" (default), the agent's own tools, or a catalog skill whose `roles` list the
      job; stored on this Mac (`agent_methods.json`), passed to the person's own agent as a sentence in the hand-off prompt,
      the stdio queue reply and one primer line — never to a remote connection, never authority. A skill the person picks
      gets a `type: skill` page tagged `agent-skill` in the graph, written only on that selection. `macos-harness` states
      plainly that it can control the whole Mac. **Extended to watching (2026-09-30, ruling 17):** the same mechanism has
      a second job, `watching` ("How your agent watches", Settings → Reading the web, under "How your agent reads"), with
      its own choice — one per job. It offers "Let my agent choose", the agent's own tools, and `watch` (claude-video),
      `browser-harness` and `macos-harness`. Backlog: **G178** (people add or import their own skills).
    Revisit when the owner asks for Route B (a Cicada-spawned browse call, spike-gated) or a per-category refuse list
    (adult, financial, health hosts: not buildable as an honest closed list, so every site the reader could not read stays
    off until the person turns it on, and every other page is an explicit ask).

15. **Continue after a plan reset — an opt-in switch, a narrow amendment to ruling 4 (owner, 2026-09-30).** The
    owner asked for it and chose the shape: a switch in *Reading options*, **off by default**, that lets **a run the
    person started** continue itself after its own plan window resets. Ruling 4 stands for everything else: a
    scheduled run never uses a plan, and a plan is never spent without the person's own start.
    **The rule.** A run the person started may continue itself after its plan window resets if the person switched that
    on for the runs they start. It never crosses a weekly reset, never arms from a scheduled run, and never changes
    engine. The switch is snapshotted into the run when it starts, so flipping it on later never arms an old run;
    turning it off withdraws an armed one.
    **The bounds** (proposed in the Sleep page v5 plan, Q-B; **confirmed by the owner 2026-09-30, "as built"**; each is a constant in
    `sleep_autocontinue.py` and a row of `test_sleep_autocontinue.py`'s table): at most **2** automatic continues per
    run; only within **36 hours** of the pause and only when the vendor **gave a reset time** (an absent one is never
    guessed); only for a **5-hour** window, the reserve line on a 5-hour window, or extra usage that then resets — a
    weekly or an unrecognised limit never arms (`agent_engine.limit_kind_of`); only while the engine the run started on
    is still what the person's own choice resolves to (label and model). The job is a one-shot `DateTrigger` at the
    reset plus a minute, recorded in the run's sidecar so a restart re-arms it, and every guard is checked again at fire
    time; a guard that fails leaves the run paused and `autoContinue.blocked` says why. If the Mac slept through the
    reset it fires on wake while still inside the 36 hours; keeping the Mac awake is not built.
    **The rail.** `run(continue_from=…)` is called from exactly two places, the Continue route and
    `sleep_autocontinue` (`test_only_the_continue_route_and_this_module_may_pass_continue_from`); the scheduler never.
    **The honest limits.** The plan's percentage covers all use of the plan, not only Cicada's; a reset the person
    slept through is still one automatic continue spent. Revisit the bounds on the owner's word, or the switch's default
    only with a ruling of its own.

16. **A scheduled cycle reads everything waiting too — ruling 4 untouched (owner, 2026-09-30).** This amends
    ruling 13's "scheduled = one batch". `sleep_scheduler` passes `drain=True` from both entry points (the daily/interval
    cron and the after-import probe); `user_triggered=False` still keeps every plan engine out, so an unattended run
    reads on the scheduled engine — a key, OpenRouter or Ollama — and **on a metered engine it spends until the queue is
    empty, with no limit Cicada sets.** That is said in words where the person chooses it (the engine menu's Scheduled
    row and Past reads' Last cycle, never a price outside them — ruling 12) rather than prevented. Consequences built with
    it: a scheduled drain pins its bank for hours and holds the same 409 on switch/export/delete as any run (disclosed,
    not fixed); a scheduled run that stops leaves a paused record and **the scheduler then starts nothing until the
    person continues or ends it** (`sleep_paused.exists`, both entry points), or a Pause would be undone within five
    minutes; the after-import probe counts *readable* conversations (waiting minus parked), so a queue of only parked ones
    never fires an empty run every five minutes; only the person's Continue can resume a scheduled run, on the manual
    engine, which can be a plan (the button names the engine). **Not built:** a spending cap or a batch cap for scheduled
    runs (owner, 2026-09-30: "no cap for now"), and "keep the Mac awake" — revisit on the first real bill an unattended drain produces.
    *Refined 2026-09-30 (final review):* the "starts nothing" rule protects a pause **a person chose or can act on**;
    a scheduled run's pause nobody chose — the process went away (`restart`, every app quit without the launchd agent)
    or the scheduled engine failed (`engine`, once at least 6 hours old so an absent engine costs one call every few
    hours) — is ended and replaced by the next scheduled run (`sleep_paused.schedule_may_replace`), otherwise one quit
    would stop scheduled reading for good. **The dotfile exception:** an explicit `CICADA_LLM_MODE=agent|codex` pin
    still resolves a scheduled run to that plan (unchanged since before G122), so under that pin the scheduler reads
    **one batch**, never a whole queue unattended on a plan (`engine_select.scheduled_plan_pin`).

    **Two amendments recorded with rulings 15 and 16 (Sleep page v5, 2026-09-30).** *G125 R10 ("one trigger, one cycle")*:
    the Sleep page gains **Pause / Continue / End this run** and a parked row's **Retry** beside its one Consolidate
    trigger (Home's and the intake card's *Read now* stay narrow amendments; every door that meets a paused run routes to the
    Sleep page instead of starting one). *P15 / R-A8*: **a stage carries a fill only when it counts something that
    finished** — Read, Sort and Decide fill from finished work; Notice and File carry no number.

17. **Video: the watch run is the person's own agent's work, the queue lives outside the bank, and copy names no
    provider (owner, 2026-09-29 and 2026-09-30, G162).** The owner approved the boards ("I also like the watch video
    designs, apply them") and, in three sentences, changed the design: no cap on a batch (ruling 13's reasoning),
    "Ollama and the rest are literally just providers. So don't assume or make the choice for the user", and "limiting
    the amount of sites makes no sense … we will never know which sites this will happen". Rulings R-VU1…R-VU10 of the
    spec stand as written except R-VU10; the three new ones are R-VU11…R-VU13
    ([`2026-09-29-video-understanding-design.md`](../specs/2026-09-29-video-understanding-design.md) §3 and §13).

    - **State is about the event, not the belief (R-VU1/2).** A video is *read* when a `video-watch` episode with a stated
      `basis` exists; the union of its episodes' facts gives `none | transcript | watched | watched_and_transcript |
      recorded`. `basis` is the agent's word and Cicada says "an agent recorded that it watched", never "Cicada
      watched"; a record with no basis is `recorded` ("method not given"), never `watched`. Nothing is stored.
    - **The queue is outside the bank (R-VU3, P4).** `$CICADA_HOME/video_queue/<bank>.json`, keys only (no URL, no
      title), flock and atomic replace, expiry in memory. Nothing in its lifecycle dirties a bank, so no route or claim
      answers 409 while Sleep runs; `cicada_video_claim` is in `WRITE_TOOLS` (the demo gate, the write lock) but
      `_writes_bank` is false for it. A lapsed lease is judged only when Sleep is not holding the pages, so a long
      drain cannot burn a video's three attempts. The `videoQueue` component carries how many leases and expiries have
      come due, because a lapse writes nothing.
    - **R-VU10, amended.** Cicada's *default* prompt never steers an agent into the person's logged-in browser for a
      video. When the person turns on the single reading permission, the prompt carries it as an instruction (their
      consent, R-RW8), never a promise, for every host: no site list, no `agent_hosts`. Owner line: 2026-09-30, above.
    - **R-VU11 — provider-neutral copy.** Nothing a video surface, the prompt, a tool description, the contract clause or
      the bridge line writes names a provider or model as the one doing the job (`test_video_copy_provider_neutral.py`).
      Names appear only as data (a harness label an agent sent).
    - **R-VU12 — no batch cap.** The queue file's ceiling is 2,000 rows, a file-safety limit with a sentence.
    - **R-VU13 — no site list for video.** An agent hands back what it cannot get with a code; the app surfaces it.

    - **How the agent watches is the same selection (2026-09-30; owner: "for now i want to use the macos-harness, the
      browser-harness and claude-video to watch videos, as selections in settings, amongst the other default options
      models can use through their harnesses").** `agent_methods` gained the `watching` job (ruling 14's skill
      paragraph). The choice — Let my agent choose (default), the agent's own tools, or one of `watch`,
      `browser-harness`, `macos-harness` — rides in the video hand-off prompt (`video_prompt.method_clause`, capped at
      130 characters so the prompt's 1,200 holds), in the stdio `cicada_video_claim` reply for a local catalog agent (a
      skill) or any local client (the agent's own tools), and in one primer line (`Watching videos`); never to a remote
      connection, never authority, and the skill is named only as catalog data (the neutral-copy lint scans templates).
      The primer budget stayed at 1,525: both method lines defer to items 3 and 9 for the tool names instead of
      restating them. Naming a browser skill here does not reopen R-VU10: the default text still names no browser
      route, and a chosen skill is the person's own instruction, carried the way the browser permission is.
      `macos-harness` says it can control the whole Mac in the picker.

    Revisit R-VU10 only if a real run shows the clause steering an agent somewhere the person did not allow; revisit
    R-VU12 only if a bank's queue file ever nears its ceiling.

18. **The study room is animated pixel art on the owner's own bookworm — state art may move, and it still shows only
    real state (owner, 2026-10-01; G176, G107, G125).** The owner: "I've already done here the base model of the
    bookworm i want. Can you iterate with codex sol 6.1 extra high effort all the sprites with the animations? and
    generate the assets like the lamp, extra books, window, environment behind window animated too. Little fly (pixel
    size almost), moving around turned on lamp. Have environemnts for sunny, night, windy, rainy... all animated. You
    will find the bookworm png and 5 emotion states here app/assets/. Make sure to generate everything, have codex
    implement it using computer use in aseprite and add it to the app." The binding spec is
    [`2026-10-01-bookworm-sprites-spec.md`](../specs/2026-10-01-bookworm-sprites-spec.md). This amends Track Z's R-Z1
    (its persist list: the held book at room scale in every state, shut eyes when sleeping, black X eyes and the drop on
    error; the nightcap retires; the stage dots persist only in the 18 × 18 set), R-Z4, R-Z11 (titles, motion and
    palette: `palette.json`, not `DeskPalette`) and R-Z12, G125 v3's R-A13 and P14, the 2026-09-02 mascot plan's R1
    (nine colours), R3 (the 24-cell grid) and R8 (250–800 ms), and the sprites brief's §4, §5 and §9 where named below.
    R-Z2, R-Z3, R-Z5, R-Z7, R-Z8, R-Z9, R-Z10, R-Z13, R-Z14, P10, P11, P12, P13 and rulings 8–10 and 12 are untouched.
    - **R-BW1 — the worm is the owner's reference.** `app/CicadaApp/Art/sprites/bookworm-2026-10-01/reference/` (the
      base model, five emotions and the menu-bar design) is the approved design: a green bookworm, charcoal-grey
      glasses, a blue book, no antennae. It closes G176 Step 1 (the round-1 directions are superseded) and replaces
      "orange glasses" (brief §4, §9). The book is the character's own in every room-scale state; P10 is about props,
      not the worm. The 18 × 18 set follows the owner's menu-bar design (head, glasses and neck in two colours) and
      shows a book only in `reading`. The nightcap retires (P14), and the room worm drops the stage dots: the stage
      strip, the sentence and VoiceOver carry the stage; the 18 × 18 set keeps them.
    - **R-BW2 — sprites are sheets, not strings.** Sources and Lua generators live in
      `app/CicadaApp/Art/sprites/bookworm-2026-10-01/`; exported PNG sheets + Aseprite JSON (tags, per-frame
      durations, slices) live in `Resources/sprites/` with `sprites.manifest.json` (generator, script, source, date,
      licence, sha256) and a test that checks every hash and that each JSON's tags are exactly the ones the app asks
      for. Sheets load only through `Bundle.cicadaResource`. One `palette.json` is read by the scripts and the tests.
      G127's seam stands: a character is a set of sheets with the same tags.
    - **R-BW3 — frame animation (the Track Z lint amendment brief §4 asked for).** Motion is sprite frames with
      per-frame durations from the sheet, on whole pixels of the one lattice, drawn nearest-neighbour. R-Z4's
      no-transform lint stays for the worm and widens to every room sprite. "≤ 3 frames × 0.12 s" becomes: a beat
      settles within 800 ms (the perk within 400 ms); a transition within 1.6 s; no frame is shorter than 40 ms or
      longer than 4 s; a loop runs 0.4–30 s — `CicadaMotion`'s sprite caps, checked against every sheet. The renderer
      key bound (≤ 256 per size) becomes a bound on frame rects and decoded pixels.
    - **R-BW4 — state art may move (R-Z12 and R-A13 amended).** A state's art may loop — breathing, blinks, page
      flips, z → zz → zzz, the weather's own loop, the fly — because the loop shows a state that is already true. It
      never adds a fact and never speeds up, densifies or brightens with a count, an age or a stage (R-Z3). A mood
      change may play one transition (a yawn into sleep, a stretch out of it) besides the cheer and the weather
      crossfade; a hydrate or a refresh never does (DR-65). Glances, sways, tail flicks and nod-offs inside a state's
      idle loop, and cloud drift inside a weather's loop, are state art (R-Z12's "no glance, no drift" is amended for
      them). Still refused: any flash or strobe (the storm flash), weather driven by a count, motion with
      no state behind it (mug steam, plant sway), and duration estimates.
    - **R-BW5 — scenery separates environment and Sleep (owner amendment, 2026-10-02; R-Z11).** The time follows
      `SceneClock`'s day · dusk · night through `SceneStore` unless Choose pins it. The five base weathers are sunny,
      cloudy, windy, rainy and curtains. Local weather (default) reads the time zone's principal city, falling back to
      How Sleep is doing when unavailable; How Sleep is doing maps the mood; Choose fixes the time and base. Running
      adds calm mist; digesting adds a rainbow by day/dusk or a shooting star at night in every mode. The legend, help
      and VoiceOver share the same time/base/source and moment text. Ruling 9 applies to every weather frame and every
      reachable worm frame in each lighting set. Pixels on the lattice only, never Meadow paintings (DR-13).
    - **R-BW6 — the room is dark iff night or rainy (owner amendment, 2026-10-02; R-A13).** Lighting is a pure
      function of time, base weather and lamp: the dark room has only faint window light and, when scheduled, the lamp.
      Dusk keeps the day-lit room. Props select `night-dark`/`night-lit`; all eight room states use matching night sheets,
      including beats and both sleeping transitions, with identical tags/frame counts/timings to day. The complete art
      layer crossfades with the pane using the existing 0.4 s token; Reduce Motion swaps instantly. The menu bar stays
      independent of room lighting. The worm's mood remains Sleep's at any hour and in any weather.
    - **R-BW7 — the five emotions map to states, once.** happy → `.happy`, `.digesting` and the cheer; tired →
      `.hungry`; worried (sweat drop and black X eyes) → `.error`; sad → the shake beat; the base model → `.awake` and
      `.reading`; mad is drawn but unused. Never random, never the clock. The menu bar gets an 18 × 18 set drawn from
      the owner's menu-bar design, with the count badge and stage dots drawn on it in code (G107 R2), and its own
      precedence unchanged.
    - **R-BW8 — the lamp and its fly.** The lamp is redrawn and still means exactly the schedule (R-A3, P11; it never
      previews). The fly is the lit lamp's art: present only while lit, inert, never in the glass or the pile column,
      resting on the shade under Reduce Motion.
    - **R-BW9 — books (P10 holds).** The worm's own book has three covers that change as he picks up the next one;
      the real pile's spines gain a pixel texture by kind (a second cue beside colour; `fitPile` unchanged). No other
      book is drawn: a shelf, cart or bookcase needs a real count and its own design round.
    - **R-BW10 — interaction is unchanged.** The hotspots stay the worm, the lamp and the window; the plant, mug, bean
      bag, wall, rug, cord, scenery, wall clock and fly stay inert (R-Z2). No click on art starts, cancels or schedules work (R-Z9).
    - **R-BW11 — Reduce Motion, Low Power, unseen.** Under Reduce Motion every sprite shows its key frame (G107 R7)
      and the yawn and stretch do not play; under Low Power every frame plays at half speed; a sprite rests while its
      window cannot be seen or a host pauses it (R-HO7's reader and policy). Each animated layer redraws only at its
      own frame boundaries. **Budget:** the room's summed sprite redraws stay ≤ 1,800 per minute in every steady
      environment/mood/lamp combination, computed from the sheets (sprite boundaries plus the clock's 60 ticks ≤ 1,800 per
      minute, tested in `SpriteClipTests`); mean CPU with the room frontmost stays ≤ 3 % of one core and within 2
      points of `dev`, measured by the owner on the demo bank before merge.
      **Player amendment (2026-10-05, measured):** moving frames swap a layer's `contents` on a timer armed at each
      boundary (`SpriteLayerPlayer`); no sprite plays through a `TimelineView`. On macOS 26 a `TimelineView` with
      entries under ~0.3 s apart drives the whole window's layout at the display rate (240 host layouts a second
      for 4 ticks a second in an isolated test; 120 renders a second on the Sleep page), so the boundary budget held
      while the page still cost 12% of a core. After the change: 2.54% visible, 2.6 renders a second, 0.83% hidden
      (the menu-bar worm). A 1 s timeline still re-renders the whole window once a second, so the wall clock's second
      hand is a layer too and the leaf redraws once a minute: 1.03% visible with the graph resting, 0 renders in 10 s.
      **Wall-clock amendment (owner, 2026-10-02):** `room-clock` is state art selected from `Date()` and
      `TimeZone.current`, not a sprite loop. Hour = `(hour mod 12) × 5 + minute / 12`, minute/second = their
      integer values. Its own visible-only `TimelineView(.everyMinute)` moves hours and minutes, and a layer
      (`SpriteLayerPlayer`) moves the second hand on every whole second (2026-10-05); no room-wide timer.
      Black hour/minute hands and a thin red second hand use dark variants in a dark room. Reduce Motion removes
      only the second hand; hour/minute keep time. Help and VoiceOver say “Wall clock, <system short time>”,
      after the window. The inert clock at `(94,34)`, 15 × 15, z1 clears every worm frame, the window, shade and pile;
      the art verifier rechecks night sheets. The manifest is 36 pairs; motion sidecars exclude the clock.
    - **R-BW12 — how it was made, and the gate.** The owner chose the tool and the model for this job: Codex
      (gpt-6.1-sol, extra-high effort) with computer use in Aseprite. This overrides brief §5's "Computer use in the GUI
      is not needed and is worse" and the handoff's model split for this job only; the small-models rule is otherwise
      unchanged. Parts are hand-correctable in the GUI; every sheet is rebuilt and exported headless so the manifest's
      hashes are reproducible. PR to `dev`; no merge until the owner has reviewed `preview.html` and the composites.
    - **Dated owner amendment, 2026-10-01 — black X eyes and one menu sheet.** Error retains its worried brows and
      drop, with the exact black diagonal Xs in both lenses; red pupils retire. `errorLensL = (10,17,5,6)` records the
      error state's widened inner left rim; common rest-registration slices remain unchanged. The 18 × 18 sheet keeps
      its dark outlines on both menu-bar appearances; no dark-bar variant.
    - **Dated owner amendment, 2026-10-02 — Settings and the weather gate.** Settings → Sleep → The scenery offers
      Local weather · How Sleep is doing · Choose, with per-viewer source/time/base preferences. Choose exposes labelled,
      keyboard- and VoiceOver-accessible key-frame thumbnails for three times and five base weathers and a small live
      room preview. Local weather discloses the public city read. The app's own weather gate is Local weather AND the
      study room visible: one HTTPS host, four seconds, at most 64 KiB, no cookies or identifiers, no redirects/auth,
      at most one attempt per half hour including failures, memory cache only; selecting another source turns it off.
      It reads public city coordinates from `TimeZoneCoordinates`, never location permission or a bank. The binding
      [`2026-10-02-study-room-scenery.md`](../specs/2026-10-02-study-room-scenery.md) supersedes the old seven skies and
      no-clock refusal. A lightning flash stays refused. Count props, the queue as a room, G175 marks and Q1 remain open.
    - **Dated timing amendment, 2026-10-02 — retain R-BW11's cap.** Independent leaves cost 1,908 boundaries/minute
      for rainy-night + digesting + lamp lit: rain 749, fly 520, worm 340, shooting star 239, clock 60. Rain's holds
      move from 80 to 100 ms in day/dusk/night, keeping all 48 original pixels/frames and every seamless motion step.
      The amended rain costs 599/minute; the measured maximum over all 240 combinations is **1,758/minute**. The
      art verifier pins 100 ms exactly and still checks the historical day-pixel hash. No cap was raised. Hidden
      rooms and Settings explicitly pass the pause to the sprite leaves as well as the clock and weather reader.
    - **Dated mascot amendment, owner 2026-10-02:** “work on the selector for the mascot in settings. Name this one
      bookworm.” The Mascot group beside The scenery uses registry entries (id, display name, room prefix, menu
      sheet, art folder), with exactly **Bookworm** today. Selection is a per-viewer preference, default/fallback
      `bookworm`; shared art readers, cover/transition timing and the menu cache resolve that entry. Tiles show
      room/menu key frames, a checkmark, keyboard focus and a selected VoiceOver label. Another character will have
      its own base and the same pipeline/tag/canvas contract, plus one entry and manifest files; no state change.
    - **Integration review correction, 2026-10-02:** room layers keep the appearance crossfade; the worm is its
      sibling, keyed only by day/dark-lit/dark-unlit lighting. Mood/overlay edges and day-time lamp toggles start
      their new frames fully visible when the lighting set stays the same. **Re-review follow-up:** an active
      transition or beat also suppresses the worm's lighting-swap animation, so error → sleeping's day/dusk
      rainy/dark → sunny/day yawn starts fully visible in Sleep-driven scenery or Local weather fallback. Room
      layers still crossfade; passive worm lighting changes retain their fade. The wall clock ticks on whole seconds (whole minutes without seconds under
      Reduce Motion). Weather sends no viewer language/region; an empty language field suppresses CFNetwork's
      default, fixed headers accompany the coordinate/condition query, and the disclosure includes the network
      address. Backwards time makes the next attempt due; stale readings remain only for an eligible visible
      refresh or an in-flight refresh, and failures/cancellation/zone changes cannot retain expired weather.
      Night book/glasses/lid/z/question/X/drop marks and fly shade occlusion are checked from the real sheets.
      Partial builds refresh saved-parts predecessors and all night exports/manifest/full verification; repeated
      night/fx builders replace prior output. Static family provenance removes the Codex CLI rebuild dependency.
    Revisit R-BW4 or R-BW11 if either half of R-BW11's budget is exceeded or a viewer reports motion discomfort;
    R-BW5–R-BW9 on the owner's word.

19. **A release is a merge to `main`, and a merge to `main` is a release (owner, 2026-10-06; G182).** This replaces
    the manual-promotion rail for releases only. Owner, verbatim: "from now on yes we merge by default to dev, but for
    releases we merge to main and automatically should be a GitHub release. So versioning should be setup properly."
    **The rule.** Every feature/fix PR still targets `dev`. A release is a PR from `dev` to `main`, opened only for a
    release and carrying the version bump; merging it is the release. CI on `main` then tags `vX.Y.Z` at the merged
    commit, builds, verifies and publishes the GitHub Release — nobody tags by hand, and nothing else reaches `main`.
    **Versioning.** `VERSION` (semver) is the one source; the app bundle, `pyproject`, the tag, the release title and
    `latest.json` must all equal it, and CI rejects any disagreement. A merge whose `VERSION` already has a tag
    publishes nothing (idempotent); a `VERSION` not greater than the latest tag fails loudly. A failed build,
    verification or publication advertises nothing (no tag, no `latest`), never force-pushes, never overwrites a
    released asset. The website's download link resolves through a stable latest-release asset, so no later release
    needs a website edit.
    **Why.** The owner's delivery priority for 2026-10-06 (G182): releases must exist, and the released version,
    `main` and the website must never drift. Before this, 0.3.0 was built and dry-run four times but never published,
    and `main` trailed `dev` by 88 commits.
    Revisit on the owner's word (e.g. a release-candidate channel or an older-line hotfix branch).

20. **G110 continuity rulings (owner, 2026-10-07): A — flush yes; B — head and tail; C — strip only what the harness marks.**
    Recorded with the build that implements them (feat/g110-gates).
    **A — amends ruling 7.** Stop stays the capture trigger; PreCompact and SessionEnd ALSO run the same deterministic
    capture as a best-effort, idempotent flush, so a turn the person interrupted before a `/clear` or a compaction is not
    lost. Every capture log line is tagged with its event (Stop / PreCompact / SessionEnd), so ruling 7's revisit signal
    (timeout `error:` lines) stays visible per event. SessionEnd posts within Claude Code's 1.5 s budget.
    **B — the capture cap keeps the head and the tail.** Over the 100k-character session cap, capture keeps the first
    60k and the last 40k (the tail advancing in blocks of whole turns) with an explicit gap marker that is never a
    speaker's words. Costs accepted knowingly (G104): a long active session is re-extracted as its tail moves; quotes in
    turns that slide out degrade to `reasoning`; the person's words that slide out of the tail leave the bank. Revisit
    if re-extraction cost on long sessions is measured as a problem (G104/G148).
    **C — clarifies G149.** A Cicada note is dropped from capture only when the harness marks it as injected (whole
    non-person records / harness envelopes). Text the person typed or pasted — even one starting with Cicada's header — is
    kept as the person's words and counted/disclosed (`note_like_turns`). G105 R5's tool-output and system-reminder
    rules are unchanged.

21. **G180 CLI rulings (owner, 2026-10-07).** **Transport:** the `cicada` CLI runs Cicada's services in-process, the
    stdio MCP's own model, under the same locks (write admission, page, git), the bank pin and `demo_guard`; before a
    write it cross-checks the backend's `/healthz` `memory_root` and refuses on a mismatch (the split-brain guard). It
    works with the app closed and in network-off sandboxes. **PATH:** an app Settings button links `~/.local/bin/cicada`
    without admin; the skill falls back to `~/.cicada/bin/cicada`. **Session:** a write from a shell with no harness
    session id omits `session_id` and the `Cicada-Session` trailer, never a per-command minted id (it would fragment the
    stream, G104). **Names:** short grouped commands (`cicada recall`, `cicada save`, `cicada claim add`, `cicada inbox`,
    `cicada sleep status`); MCP tools keep the `cicada_` prefix, and grouping them is the lean-MCP slice, decided on
    measured schema numbers with old names kept as aliases. No generic `call <tool>` door.
    **Why.** Over HTTP nothing works with the backend down and sandboxed shells cannot even read; in-process is the
    MCP's proven model, and the root check closes its one gap.
    Revisit if the CLI and the backend are measured to disagree on a bank in practice, or for a server package (G181).

22. **G110 slice 1b rulings (owner, 2026-10-07).** **D1:** capture keeps up to ~16k characters of the person's FIRST
    message in a session (other turns keep the 2k clip), inside the session budget and with the same scrub, so a long role
    or objective can be continued; the Sleep cost is measured before shipping. **D2:** amends slice 1a's "no `.git`
    reading anywhere" for the hook alone: a bounded, read-only, fixed-command git identity observer may run harness-side
    and send plain values (repository root, worktree list); the backend never reads the person's folders and only parses
    what is supplied. **Requirement restated:** no handoff prompts; a fresh session in Claude Code, Codex, Cursor or another
    harness continues the role and the work (G110 row).
    **Why.** The owner's acceptance example is an orchestrator whose role came from a long first instruction and whose
    workers run in sibling worktrees; the 2k clip and exact-folder matching each break it.
    Revisit if the first-message exception is measured as a Sleep-cost or privacy problem.

23. **Memory-quality rulings (owner, 2026-10-09).** **Engine:** Sleep runs on the owner's Claude plan with Haiku 5.5 for extraction and disambiguation, at concurrency 10 (Sonnet measured ~15 min per 25-conversation batch, Haiku ~9). **Skills (G112):** a Stage 4 skill needs two or more conversations, a one-conversation skill is held in `skill_hold`; skill pages whose sources cannot be traced are archived (44 on the owner bank); no contradiction check on skill updates; possessive aliases ("my mom") are kept, a reference phrase is never an alias. **Pages (G194):** summary synthesis is on for the owner's install — one bounded summary per page and paraphrase folding, its calls overlapped (#258); the rule-based fact fold drops a fact only when it **equals** one already kept after trivial normalization — never containment, never stopword or preposition stripping. **Search:** EmbeddingGemma 2 is downloaded only when the person asks, never automatically.
    **Why.** Two review rounds showed every containment rule dropped a fact that said something different ("works at X" inside "works at X's competitor", a from/to swap, "1,200" vs "200"); a duplicate is cheaper than a lost fact. Synthesis-on costs ~1,000–1,500 calls per full run (clean run: 742 page updates) and is the only place paraphrases fold. An automatic 585 MB download would be a new automatic network behaviour.
    Revisit the fold only with a measured loss-free paraphrase rule; synthesis if its call count per run is measured as a plan-limit problem.
24. **Pages, age, pictures and the CLI (owner, 2026-10-09 to 2026-10-13).** **Pages are articles (G194):** a lead and prose sections with no length cap, written for pages on 2+ conversations (amended 2026-10-17, owner: "uncap what the agents can write to" — also for a page on one conversation, a new page included, whose record holds `CICADA_PAGE_ARTICLE_MIN_MATERIAL` inputs; a stub below that stays the merge), over a record (Key Facts, History, Links, Open Questions, claims) that is unioned and never shortened; provenance per paragraph; an edited article is the person's. **Age counts from when it was said (G170 amended):** what the conversations prove silent is charged once, when read; a one-off may archive by age; a page or claim on 2+ dated conversations floors at 0.39 and only live silence archives it; a mention never lowers; a decay question only when live silence crosses 0.4. **Pictures (G159/G162):** Gravatar (the owner's hashed email) and GitHub for people, X and LinkedIn through unavatar.io behind their own default-off gate as the ToS rail's one exception — only from a link given as the person's own account; link-card icons only from the page's own tags; a YouTube still from its id when oEmbed gives none. **CLI (ruling 21a):** commands on state the backend owns go through its routes after `/healthz` confirms the root; person-only commands refuse from an agent's shell. **Web:** keep the door open — new features live behind the backend API, no browser front end yet.
    **Why.** Pages: rich pages had a median 26 facts and a 36-word summary because the merge prompt capped summaries at 1–3 sentences; the owner pointed at gbrain and Cognition's agent-memory repo — free prose, git as the safety net. Age: the owner's own reading ("if we track the time where i did that work, then it would be irrelevant now"); a straight age rule archived 79% of the bank (601/664 projects) in a dry run, so repeats floor. Pictures: the owner's own chain from another app, minus guessing. CLI: one implementation for the app, the CLI and a future browser front end; no second Sleep.
    Revisit articles if G148 measures a recall loss or the plan limit bites; the age floor if the owner reports losing things he needed (count revivals first); the unavatar exception if the provider changes terms or starts scraping behind a login for X.
    **Amended 2026-10-16 (owner: "Yes I agree with read on time then") — read on time.** A conversation read late (a newly connected source's history, an export imported later) counts as if Cicada had read it the day it was said: when a conversation is read never changes where a page or claim ends, only when it was said does. Before, one dated before a page's watermark added its source and week and moved nothing, so a page decay had lowered stayed faded although a newly connected chat had mentioned it three days ago. Now the decay pass places it (`read_late` → `conflict_resolver._revive_on_time`, `claim_reconciler._place_on_time`, one `decay_policy.on_time`): revived on its day (a page to 0.6, a claim to its restatement's confidence), less proven silence (repeat floor) up to the day the page's previous mention was read and live silence after it, through the watermark plus at most one pass (ruling 1); only raises; a lift left below 0.4 and heard late is `faded_by_age`. To keep it order-independent a live mention now raises any settled page to `max(current, 0.6)`, active pages included (G66 §1.6 had raised only decaying/archived ones), and a settled claim restated after its watermark but read days later is placed on the day it was said instead of restarting the day it was read. Existing banks: `api/scripts/recompute_read_on_time.py` (dry run by type, `--apply` one `cicada` commit). Revisit if the owner reports pages coming back he considers stale (count lifts by age of the mention first).
25. **Exploring saved sites (owner, 2026-10-14; G166, G196 open question 2).** **D1 storage (b):** one thumbnail per
    changed look in the bank, full images in `~/.cicada/captures/` outside git, kept and exportable with the bank;
    deliberate Looks keep their full image in the bank. **D2 browser context, amended by the owner:** "My signed-in
    sessions by default, but I can choose to disable this in Settings" — agents explore in the person's everyday
    signed-in Chrome session and every capture taken signed in is marked `signed_in: true`; the Settings switch (Reading
    the web) turns it off, and off is a private, cookie-less browser context (`Target.createBrowserContext`, verified
    drivable through browser-harness in a test Chrome; an agent that cannot open one hands the site back, never falls
    back to the signed-in session). Still binding: private workspaces excluded; walls and captchas recorded
    `needs_login`/`blocked`, never retried with different headers; consent banners never clicked or hidden; one agent per
    site, ≥ 8 s between pages. **D3 consent (a):** the reading acknowledgement is v3 with an exploring paragraph saying
    plainly that exploring uses the signed-in session by default and the person's accounts carry the terms-of-service
    risk, plus a per-site *Never explore*. **D4 depth (a):** a scripted capture of the viewport and metadata by default;
    Sleep's recon finds the relations; full page, mobile, dark and second pages only where the person's why (G191) asks.
    **D5 who starts (b):** the person's click, or a trusted local agent they asked in chat, stamped with who started it,
    shown at once and stoppable in one tap; never remote, never from an agent's shell. **D6 change detection (a):**
    Cicada's own fetcher may check an explored public page at most monthly on the Sleep tail, under the connector gate
    and the ToS rail, and only marks "may have changed" — slice 3.
    **Why.** The design (2026-10-14) measured ~1 GB of images a first pass of 1,000 sites, which in git would grow
    forever (ruling 3's failure); the owner wants his logged-in view of the sites he saved, accepting the account risk
    in words he signs.
    Revisit D2's default if a capture taken signed in is found to have kept another person's private data in a bank; D1
    if exported banks are measured to miss the full images people want.
26. **Tracked sources: update, dated; the newest evidence wins (owner, 2026-10-14 evening; G61, amends the S3 rail).**
    Owner: "Marking a dead site and being able to recheck a website after a certain time to see any updates … If I have
    the LinkedIn of a person … I know that through LinkedIn I'm going to get it … being able to update these things
    through consolidation would be nice." **What is re-checked:** a source the person added or took, or one Cicada's
    own read confirmed (the existing trust rule), monthly by default (a per-source cadence) or when the person asks.
    **What a re-check produces:** a new dated fact with the page and the capture date as evidence; the old fact's
    validity closes (bi-temporal, nothing deleted); provenance is the agent or Cicada, the source, the date. **The newest
    evidence wins, even over the person's own words** (owner amendment, same evening: "it can override something I
    said if it has evidence, there is no problem with that"): a re-check dated after the person's statement supersedes
    it and the statement stays as history; a statement dated after the capture stands; only a clash with no clear order
    (the same day, or an undated statement) becomes one inbox question with both sides and their dates; nothing changes
    silently (the page and the timeline say what changed, from where and when; git reverts it). **Dead:** "gone" needs
    two failed visits a week apart (not found, gone, parked, moved); marked dead with the date, the last good capture
    kept. **Who checks:** public pages, Cicada's own fetcher on the Sleep tail under the connector gate and the ToS rail;
    login-walled sources only the person's own agent, through an explore-style queue, in the signed-in session per
    ruling 25 D2 and its switch — Cicada never fetches them. **Ruling 4 holds:** due checks are only listed; the agent
    works them when the person asks or when the hook's one line ("N tracked sources are due for a check") leads them to.
    The inbox check (G61 S3) is unchanged: it still settles nothing.
    **Why.** The owner tracks facts that change at their source (positions, roles) and wants memory to follow them
    without maintenance; the S3 rail had been written for a check proposing an answer to an open question, where a
    planted source could steer a belief — a dated re-check of a source the person chose is evidence he accepts.
    Revisit if a re-check is found to have overwritten a statement the person had to restore (count the divergence
    answers and `git revert`s of `Source refresh` / re-check commits first), or if a site's terms change for the walled
    family.
27. **A web lookup settles questions about public things (owner, 2026-10-16; G61, amends the S3 rail).** Owner: "A web
    lookup answers 'what is X' for public things and closes the question. The answer is saved with its link and quote,
    and you can undo it from a 'Settled by a check' list. Never searched: people's names, your own files, your projects,
    your life. Runs from your Claude plan in runs you start; a scheduled metered run costs a few cents more." Refinement,
    same day: the answer carries a citation (the URL and the short quote, shown where the claim's evidence shows) but is
    **not** a tracked source — it never joins the page's re-check set, never makes a site trusted, never drives a logo;
    the person may promote it with one tap. **What:** a pending conflict or clarification about a work, product, tool,
    company, public concept or paper; never a person (typed, an untyped name whose description says so, a person's name
    or alias), the owner's page, a file or path, a project, anything only the conversations know; when in doubt, the
    question stays. **What leaves the machine:** the subject's name plus generic category words — never conversation
    text, never another name from the bank, never the person's name. **Who:** Sleep's tail on a run the person started,
    with the Claude plan's own search as the call's one tool (ruling 4: a scheduled run never uses a plan); a metered
    engine's own search at its price, priced in Past reads (ruling 12); `CICADA_ALLOW_CONNECTOR_FETCH` gates it; the
    person's own agent through `cicada_record_check(outcome="settles")`; questions about whether a PR or a G row merged
    are answered from the commit by a trusted local agent, never searched. **Settling:** a claim (observer the agent,
    the citation as its evidence), the question resolved and listed under "Settled by a check" with one-tap undo that
    takes back only what the check wrote (and marks the question so no check settles it again). The S3 rule stays true
    for everything else: an inbox check on any other question still settles nothing. **What a thing is** (owner, same
    day, his own example "Is <tool-a> an agent harness or an AI agent itself?"): a type/`is-a` conflict is eligible
    though `is-a` is multi-valued; it settles on one option only when the cited page rules the others out, on the
    item's own "both" option when the page supports both, and never on an option Cicada invents.
    **Why.** About 60 of 126 open conflicts and clarifications on the owner's bank (2026-10-16) asked about public
    things a lookup answers, and the person was asked to look them up by hand.
    Revisit if an undo count on `web_check` rows (ids only) shows settles being taken back often, or if a settle is
    found to have searched or written something personal.
    **27a — local context (owner, 2026-10-16: "Yes, use local context").** The model may read what Cicada already
    knows about the subject — its page's one-line description and up to two lines where it was mentioned (the item's
    conversation, its option claims' evidence), ≤ 600 characters, scrubbed as every writer scrubs, people's names,
    links, addresses, handles and paths taken out (`web_settle.local_context`) — **to judge which search result is the
    right one**. The search query stays the subject's name plus at most ONE generic category word, checked word for
    word (any other query settles nothing); the word comes from Cicada's own description, never from the page's type
    alone, never on a question about what the thing is, never one an option label carries — a bare name when unsure.
    Clarifications are looked up before conflicts; conflicts with a mention line before those without. **Why.** The
    first person-started run looked up 8 questions: 8 searched the pinned query, 0 settled, all unsure; a replay with no
    writes found 69 eligible (31 type conflicts, 1 other conflict, 37 clarifications), three clarifications replayed
    all unsure. The model saw only a name that also belongs to a restaurant, a town or a product, often with a wrong
    category word, and was right to be unsure; only the person's context says which thing was meant. The same engine
    already reads those conversations during Sleep, so the prompt sends nothing new anywhere and what reaches the
    search provider is unchanged. Measure with `api/scripts/web_check_dry_run.py` (counts only, writes nothing).
    Revisit if the dry run on the owner's bank still settles none, or if a prompt is found to have carried a person's
    name or a path.
    **27b — the inbox is not for what a search answers (owner, 2026-10-19): "Questions like 'Is <a public tool> an AI
    agent or an AI code editor?' can be solved by an internet search. That's not what the inbox is for."** The lookup is
    the default path for a clarification or conflict about a public thing in every Sleep run on a plan — the person's
    and, with 4c, the scheduled one — and the backlog already open gets a one-off sweep the person starts
    (`POST /inbox/web-check`, dry run by default; `api/scripts/web_check_dry_run.py` for counts with no write): same
    eligibility, pinned query, local context, citation and "Settled by a check" undo; each settle under the bank's write
    admission with its own commit; a plan limit stops it. A search that cannot settle a question confidently leaves it
    exactly as it was. Stage 1's way of naming the speaker ("the user mentioned it") no longer reads as a person cue,
    and a description saying the subject is the speaker's own (built by the user, the user's project) now keeps it home.
    **Cicada's own settings are never asked:** a conflict or clarification on Cicada's own page (exact id) about its
    runtime settings — which engine its Sleep runs read with (a plan, an API key, a local model), whether scheduled runs
    use the plan, the schedule's time — is retired by rule, nothing else touched (`inbox_tend`'s `own_settings`, undoable under
    "Settled by Sleep") and never searched — the system knows its settings and Settings shows them, and a conversation
    that mentioned them stated that day's configuration, not a fact for the person to referee (never "answered from the
    system": writing today's config as a claim would date a past statement wrongly). Narrow on purpose (review of #360):
    the owner's project IS Cicada, so its design questions (a hosting provider, a page's layout, the search or graph
    engine, whether Sleep runs nightly) stay his; and the speaker's own thing in the active voice ("an app the person
    is building", "the company where the person works") stays home too. Revisit if the sweep's dry run on
    the owner's bank settles under a quarter of what it looks up, or if an own-settings dismissal is undone.
28. **Headless clients (owner, 2026-10-16; G181 phase 2, amends the transcript rail and ruling 21a).** **1 — Per-device
    tokens.** A second device never gets the server's master token: each gets its own named, hashed, revocable token
    (`device_tokens`, the G135 store's shape kept apart). Issuing one is an act of the person — `cicada device add` on
    the server or `POST /devices` with the master token — never automatic, never by an installer, never by a device
    token. **2 — The transcript rail, amended.** A harness session is read on the machine where it lives, by Cicada's
    own extractor, and posted as scrubbed, capped turns (`POST /capture/session`); ids are minted on the server under
    its lock, so one episode per session (G104) holds. The backend still never opens a path a remote client names;
    same scrub, caps, G110 markers and demo rule, re-checked on arrival. **3 — A tailnet device counts as local for
    the G198 trust list.** A trusted harness (Claude Code by default) on a device holding a token the person issued
    edits pages at once, exactly as on the same machine; the G135 remote connector and the `agent` author stay off the
    list. **How the server knows (worker's decision, 2026-10-16):** from the token alone — `auth.require_token` looks
    the bearer up and records the device on `request.state.device`; the tool door runs the call as a local stdio call
    (no `connector_id`), and the device id is written as `device:` on what it writes. Nothing a client puts in a header
    or body can claim a device, because a claim is not evidence and the token already is. **21a, amended:** the CLI
    compares a bank identity (an `id` per bank in `banks.yaml`, minted by the backend), not a path; a client pins the
    server's bank by name and id and names both on every write.
    **Why.** The owner wants a home server holding the bank with Sleep running uninterrupted and the Mac as a client
    (research `2026-10-15-headless-server.md`, option C); a copied master token could not be revoked per device, a
    path posted across machines cannot be opened, and a path compared across machines means nothing.
    Revisit 2 if a client's extractor is found to have sent something the server-side extractor would not keep (the
    `turn_over_cap` refusals in the capture ledger are the signal); 3 if a device token is found in the hands of
    anything but the person's own machine.
    **Phase 3 (worker's decisions, 2026-10-16):** a device token may READ `GET /devices` (ids, names, times, and
    `current` for the asker) so the app on any of the person's devices can show them; issuing and revoking stay the
    master token's (1 unchanged). The device a request came from is bound for the request (`device_context`) and
    stamped on every new episode it causes, except Sleep's run, which clears it. The app's server setting is a file the
    hooks read too (`$CICADA_HOME/api_base`), so one switch moves the whole Mac; `CICADA_API_BASE` still wins.
    Review (2026-10-16): the click writes `api_base.next`, moved into place at the next launch, so the agents never
    switch before the app; a background service is stopped on a server (plist kept); a reader's newer post never
    overtakes a waiting one on its route; provenance and Reader ETags carry `device1`.
29. **Sleep tends the inbox: questions get answered as conversations come in, the small stuff is assumed (owner,
    2026-10-17; amends G21, G113 and the "Clarification queue over silent drops" decision).** Owner: "a single
    consolidation also should take care of cleaning up the inbox. … I think it was part of my thesis also that sleep
    would also take into account the inbox so that, as conversations come through, questions get answered. There are
    also many things that maybe can be assumed, like they don't have to be explicit, and I think a lot of cleanup can
    happen in the inbox for actually necessary stuff for the user. There are little things that are honestly not that
    big of a deal." And: "We can do everything with my Claude plan." **1 — Answered in conversation.** Every batch, for
    the open conflicts, clarifications and duplicate questions its conversations are about (the ask gate's rule, over
    the person's own turns), the engine reads the person's lines and copies the words that answer one; a question is
    settled only when those words are found exactly in one of the person's own turns (spans, never a guess, never an
    agent's words); the conversation that raised a question never answers it. **2 — The small stuff is assumed**, once
    per drain and by the one-time tidy: a question whose subject is gone; a duplicate with the same name once spelling
    is folded, or one the judge reads as the same (≥ 0.9, both pages, same type) or as different; a predicate fold
    that only respells a label; a decay question on a one-off nobody would miss (a concept, tool, media or company page
    on one conversation, never kept, no words of the person's on it); a conflict the newest dated statement settles
    (never a machine claim over the person's own); a conflict on a multi-valued predicate (every value already kept).
    **The judges (owner, same day, after the first dry run on his bank: "the inbox keeps only what genuinely needs the
    person"):** behind `judge=true` / once per drain, the person's chosen engine (plan included) also reads conflicts
    (each option's dates and evidence lines; one clearly better supported or newer, never a machine claim over the
    person's own), label folds (same meaning folds; a changed meaning stays) and fading concept/tool/media/company pages
    (still live → only marked active: no mention dated today, no claim reopened, no confidence lifted; clearly passing →
    archived); each judged settle shows the
    judge's one-line reason. **Never assumed:** who a person is or merging two people (only the
    person's own words on the record), a proposed page edit, a follow-up (only the person's own words, part 2), anything a rule cannot read — those stay.
    **One writer:** the person's own resolvers, committed as Sleep's (`Inbox settled by Sleep`, `inbox/<kind>/settled:`,
    never `resolved:`), each undoable under "Settled by Sleep" (the reverse of its commit, three-way, refused whole when
    something since overlaps); an undone question is never settled by Sleep again. The G113 ledger keeps Sleep's settles
    and the person's undos apart from the person's verdicts (`sleepSettles`). **Engine:** the batch's own (ruling 4
    unchanged); the tidy uses the person's chosen engine, their Claude plan included; a plan limit pauses, never fails.
    **Review (same day):** a "same" on two existing pages folds the duplicate's page into the target (undo brings it
    back); each question is decided and settled at once and only while every page it read is unchanged, under the page
    lock. Re-review: a claim resting on the person's own words (their inbox answer or a span in their own turn) is closed
    only by one that does too or by a tracked source's dated re-check (ruling 26).
    **Part 2 (owner, same day: "a lot of cleanup can happen in the inbox for actually necessary stuff for the user"):**
    a label-only conflict (no option carries a claim) is judged through the page's open claims its labels are tied to by
    folded words (never fuzzy; a side nothing on the record states is never picked; the owner's-words rail holds over
    the tied claims). A page-bound question whose page is gone retires (`subject_gone`); one whose page cannot be parsed
    never does. **Move 3 — answered already, anywhere in the record:** a clarification, follow-up or conflict still
    open is looked for across the whole bank (the page's own pointers plus the lexical index by its spellings), settled
    only on the person's own words located exactly in one of their turns (kind `user`, never an agent's, never fuzzy),
    recorded as the evidence span; a conflict only by words said after every side of it, a follow-up only after its
    thread was last heard and only done/still/stopped (or done/missed/dropped), dated the day it was said. Sleep: 4 per
    drain; the tidy: all, behind `judge=true`.
    **Part 3 (owner, same day: "little things that are honestly not that big of a deal"):** a clarification about a
    name with no page, said in one conversation and only in passing there (≤ 2 exchanges name it), with nothing tying
    it to the person's life, closes as mentioned in passing (`in_passing`: the person's own dismiss; nothing written
    about who it is; it may be asked again when another conversation names it); a code identifier however often it is
    named. Never a relation question, a project/skill/deadline, a person said in any of the person's own turns
    (review: a relation a sentence away, a dropped Spanish pronoun, or none at all — their words mean the person may
    be in their life), a relation word or (for a company or place) first-person words in the naming turn or the turns
    beside it, a name on the owner's page or from a Messages chat. A label-only
    conflict is settled by the person's newest words (`newest_words`): their newest plain statement of one side (the
    sentence names the subject; no negation, modal or avoidance, read on the raw text), newer
    than any line or belief for another side and with an older one on record, located exactly in their own turn,
    dated that day; when not mechanical the conflict judge reads those lines and may rest its pick on one, under the
    same guards. Measured (owner's bank after #338, counts only): 59 of 69 clarifications asked with nothing on the
    record, almost all names said once in passing; 40 of 58 conflicts `labels_not_on_record`.
    **Why.** On the owner's bank (2026-10-17, counts only): 913 pending question files and 0 answered — 661 duplicate
    questions, 70 conflicts, 69 clarifications, 63 decay, 46 predicate folds, 3 proposed edits, 1 follow-up — served as
    239 rows after grouping, over 4,693 pages (2,221 archived, 823 decaying, 1,649 active). The first engine-free dry
    run (no judge): 692 of 913 settled (660 dead duplicate questions), 221 still asked — the judges are for those. UX principle 1, "never
    require memory maintenance", was broken by the inbox itself. Measure with `api/scripts/inbox_tidy_dry_run.py --bank
    <path> [--judge]` (counts only, writes nothing). Revisit a rule if `GET /consumption/feedback`'s `sleepSettles`
    shows the person undoing it often, or at once if a settle is found to have decided who a person is without their
    own words.
30. **Watch history and export saves are indexed, not consolidated (owner, 2026-10-18; G71, G94).** Owner: "maybe
    overanalyzing the watch history is too much … Maybe just have it there and then maybe the metadata has it as
    embeddings or something." **1 — A record to look up.** A watched day, a month's summary of them and a save from a
    platform's saved list (a Takeout playlist and Watch later through any door, Instagram saves and likes, TikTok likes
    and favourites, an X archive's likes and bookmarks, Reddit's and LinkedIn's export CSVs) are never read by a model:
    captured already read (`processed_by: index`), retired by Sleep before a drain freezes when an older bank queued
    them, and excluded from every "waiting for Sleep" count (`history_index.waits_for_model`). They stay files — saves
    in Saved with their metadata — found through the lexical and vector indexes, recall's excerpts, Ask's read of the
    record and the timeline's count. A browser bookmark, a single URL save, a connector poll and any save carrying
    the person's own note are read by Sleep as before. **2 — The signal is counted, not read:** one summary per
    platform per month (the channels watched most, the ones come back to across weeks, the videos watched on more than
    one day, each day's count), deterministic and order-free. **3 — A watched day is not a mention:** history never
    writes a page (no claim, no source episode, no date, no lift, no page minted, no inbox question) and never touches
    decay — a watch is a record the platform kept, not the person's words (the memory-export precedent), often autoplay,
    and at 45k watches would hold every same-named page at the repeat floor for good; a page named like a channel gets
    one derived line at read instead. **Proposed, not built:** a playlist the person named themselves (not Watch later,
    not Liked videos) as a light interest signal — its name and size in the month summary or one line on the owner's
    page, still with no per-video model read. **Why.** On the owner's bank (counts only): 45,879 watches → 2,532 day
    episodes, 3,156 playlist saves (31 playlists; Watch later 1,415), 2,444 → 5,094 episode files, 5,692 queued for a
    full Stage-1 read each. Measure with `api/.venv/bin/python -m api.scripts.history_index_dry_run --bank <path>`
    (counts only, writes nothing). Revisit if the person asks for a playlist or a stretch of history to be read, or if
    the month summaries prove too thin to answer "what was I into then" — then a bounded, opt-in read of a summary,
    never of every day.
31. **Plan-first engines: never a metered key by itself (owner, 2026-10-19): "OpenRouter, eliminate it as the default.
    Just have it as an option but the defaults now are either the Claude plan or the Codex/ChatGPT plan."** The shipped
    `llm_mode` is `auto`: the Claude plan, else the ChatGPT plan, else a running local model — and **no engine** rather
    than an API key nobody chose (`engine_select.NO_ENGINE`; a resolved copy carries `no_engine_reason`, and every call
    built from it refuses before anything is sent, `providers.resolve_llm_fn`; so does a call from an Auto nobody
    resolved, whose engine label reads `auto`, never the metered engine). A run with no engine stops before Stage 1
    and says so with the fix; Ask says it has no engine; a schedule says so (`no_engine`). An API key (OpenRouter or any
    other) reads only when the person chose it — `CICADA_LLM_MODE=byok` or the picker — and stays one tap away. A plan
    the person chose, on a schedule their switch closes, has no engine rather than falling to the key. No install script,
    onboarding step or Auto rung picks a metered key. **Why.** The owner's scheduled runs had been reading on a metered
    model he never meant as the default while his plan sat idle, and their web lookups were skipped for it.
    Revisit if a person with only a key is found stuck because nothing told them to choose it.
32. **Phone and web apps sign in, and conversations there are captured as they happen (owner, 2026-10-19; G135,
    amends G105 for hookless apps and the headless "never funnel" line).** **1 — Sign-in.** claude.ai (web, desktop and
    its iOS/Android apps) and ChatGPT add Cicada as a custom connector through OAuth: the G135 listener is its own
    authorization server (DCR or a Client ID Metadata Document, PKCE S256, short-lived access and rotating refresh
    tokens that map to the existing hashed, scoped, expiring, revocable connector rows). The person runs a public
    tunnel with a stable hostname (Tailscale Funnel or ngrok) **to the G135 listener only** — its port serves MCP and
    sign-in and nothing else; the backend's own port is never funnelled, and Cicada never starts a tunnel. **Consent
    happens in the Cicada app on the Mac** (or the local API on a server), never by a password on the public page: the
    public page shows a short code and waits, and the person approves by **typing that code** — never by clicking a
    listed request, and a self-registered app is never named or branded by what it claims (security review of #359:
    the flow's initiator collects the result, so a click-to-approve list let a stranger's look-alike through). The secret-link door keeps working; the docs steer to sign-in, because a
    link is a credential in a URL. **2 — Real-time capture is the usual; exports are a starter seed.** Owner: "Exports
    should only be a starter seed for users; the usual should always be real-time captures." For apps with no hook,
    the connector's contract asks the app's model to call `cicada_capture_turns` every turn with the person's message
    verbatim and its own previous reply — the one capture that depends on a model calling a tool, taken knowingly
    because those apps offer no hook. **Default until the owner says otherwise (coordinator, 2026-10-19):** relayed
    words are that conversation's episode with its channel disclosed (`relay`), but are **not** counted as the person's
    own words — not for promotion's own-words rung, not for ruling 29's settling — because a model can paraphrase; a
    later export import of the same conversation de-duplicates against it and upgrades it in place. **Revisit** when
    the owner rules on whether relayed words may count as his (trigger: a measured paraphrase rate on real relays), or
    when an app ships a hook or a conversation id Cicada can key on instead of the first message.
33. **Contacts as a seed, and imported-only pages that stay quiet (owner, 2026-10-20; G154, amends the promotion rail).**
    **1 — Cards wait, and a card is matched on mention.** Never one page per card. Every card that matches no page waits
    outside every bank, in the people directory LinkedIn connections already use (`$CICADA_HOME/people/<bank>/`,
    `people_directory`), with only what G154 posts (names, which facts the card holds, a thumbnail); every sync
    rewrites the set, deletions included, and the bank gets nothing for a waiting card. The first time a conversation
    names that person in full (given + family, either order, folded) or by an alias, and exactly one card carries the
    name, that alone promotes the mention, and the page is born with the card's name, photo and G61 sources. Never a
    one-part name, a name two cards or two pages share, a relation-only person (`role_people`), or the person's own
    card: the "me" card belongs to the owner's page (G169) and never waits. Sleep's tail matches the cards still
    waiting against pages born later, as LinkedIn does. **2 — Pages that exist only because of an import (saved
    videos, playlists, saved links) are dimmed until the person mentions them.** The first mention lights the page; a
    quiet page is never asked about in the inbox. The rule chosen (`quiet_pages`): import evidence on the page itself
    (its `media:` block, or a save or watch among its own episodes) and no conversation evidence (no other episode
    among its own or its claims', no claim citing a person's own words); Cicada's own checks count for neither; the
    owner's page never. Derived on every read, never stored, so the first mention ends it with nothing to write. Demo
    bank: 74 pages, 7 with import evidence, 6 quiet (the seventh is the saved guide the demo person talked about).
    Decay is unchanged (classes, rulings 1 and 30). **3 — The notes field: not now.** Nothing new is read from a card
    beyond what G154 reads. **Revisit** the quiet rule if a measured bank shows imported pages the person did talk
    about staying quiet (the trigger: a page whose conversation Sleep read but did not credit to the page).
34. **The video queue's lease findings, and which day an episode id carries (acting owner under the owner's standing
    go, 2026-10-22; G162, the 2026-10-22 Hyrum audit A5).** #399 model-checked the lease lifecycle and left four
    findings with strict-xfail repros (`api/tests/test_video_queue_formal.py`) and the decisions to the owner. Taken
    as recommended: **F1 — a per-claim lease token.** `cicada_video_claim` hands each leased row a token; a release or
    record ends a lease only with that row's token. Comparing session ids was model-checked and rejected (`F1s-*`): a
    shared id lets one conversation release another's lease, and a caller with no stable id (the CLI, remote
    connectors, other stdio harnesses) or a new id after a restart could never hand back its own (P13). A tokenless
    release answers `not_yours` and the lease lapses on its own clock. This also closes **F5** (two remote
    conversations sharing one session id). It changes the release contract, so the tool description and `mcp.md` say
    it in the same PR. **F2 — a bug; fix it.** A stale saved snapshot must never drop a queued row (it is data loss,
    however narrow the window). **F3 — accept.** A record written in the 0.1–3 s before the person queued the same
    video does meet the request; take the microsecond `requested_at` only if a lease is ever seen ending because of it.
    **F4 — cap a lease at three lease periods from its first claim.** A session that keeps calling no longer holds a
    video forever; the cap is a constant beside `LEASE_MINUTES`. **A5 — an episode id carries the conversation's
    local day** (the person's zone at the conversation's first turn), the rule every writer but the two hook writers
    (`transcript_capture`, `telegram_capture`) already follows. Why: ruling "read on time" (2026-10-16) counts a
    conversation as read the day it was said, and the person says days in their own zone; a UTC id dated words said on
    the local 22nd as the 21st. Existing ids are never renamed; the two readers that take the day from the id
    (`ask_sources`, `benchmarks/hard_questions`) read the episode's `timestamp` in the person's zone instead.
    **Revisit** F3 if a lease is seen ending on an older record; A5 if a person who travels across zones finds a day
    split wrong (the trigger for storing the zone on the episode).
35. **The skill lifecycle: candidates in Cicada, a small proven set in the harness, retired when the model catches up
    (owner question 2026-10-22, decided by the acting owner under the standing go; G112, G201).** The owner's worry:
    "as Claude Code and the models improve, a skill that once patched a gap starts pulling agents back to outdated
    behavior … the model absorbs what the harness used to patch, and the patch should then be deleted." The proposed
    shape is adopted with five amendments. **1 — Three stages.** *Candidate*: lives only in Cicada (`skill_hold`, skill
    pages, agent drafts) with the conversations it came from; never in a harness folder. *Promoted*: in the owner's
    skills repo with an `evals/` folder (skill-creator's layout, runnable with `claude plugin eval`), installed through
    the Skills page pinned to a commit (the existing consent rail). *Retired*: uninstalled from every harness; it stays
    in the repo's history and in Cicada with the evidence that retired it, never deleted. **2 — The promotion gate**
    is the skill's evals beating the no-skill baseline on the model the harness runs today, by more than the
    run-to-run spread over at least three runs each — the owner eval moved ±4 of 60 between identical runs (#370), so
    one run proves nothing. **3 — Proven-on.** Each promoted skill records the model id and Claude Code version it was
    proven on in a sidecar beside its evals (`evals/proven.json`), not in `SKILL.md`, which stays portable. When
    either changes, Cicada reruns that skill's evals with and without it (scheduled, on the plan per ruling 4c, one
    batch per change); if the baseline is now within the spread of the skill, the inbox asks to retire it, one tap,
    undoable. Never retired without the person. **4 — The usage signal** comes from the harness, not the model: the
    Stop hook already keeps each agent turn's model and effort (ruling 11); it also keeps the names of skills that
    turn invoked — names only, no arguments or output — and the telemetry ledger counts fires (ids and enums only). A
    promoted skill unfired for 8 weeks gets a retire suggestion; a "keep" answer counts like a decay keep (`kept_on`),
    so a rarely needed but critical skill (a release procedure) is asked once, not every week. **5 — Two kinds.**
    Sleep tags a candidate `about-you` (the person's preferences, people, projects, their own workflows — what Cicada
    is uniquely placed to know) or `generic` (how-to-code corrections, which models absorb fastest); the person can flip
    it. A generic skill expires by default: it must re-pass its gate at each model change, and is proposed for
    retirement 90 days after its last proof. About-you skills never expire by age; only usage or the person retires
    them. **6 — A small installed set.** The Skills page shows the installed set's weight (descriptions' tokens loaded
    every session) and asks before a promotion that takes the set past 12 per harness; by Hyrum's Law every installed
    skill becomes behaviour agents lean on. **Also:** Cicada's skills inventory must see Claude Code plugins (their
    skills and versions, read-only from the plugins' own manifests) before it can reason about the real harness —
    the first slice of G201. **Revisit** the 8-week and 90-day figures after the first two model changes with the
    sidecar in place; the cap of 12 if the owner's proven set outgrows it with evals still winning.
