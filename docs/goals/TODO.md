# Cicada — priorities and handoff

**Updated 2026-10-06. Today’s delivery priority:** G182 — make GitHub releases work today, automatically keep the released version/`main`/website links aligned, and complete the per-integration post-consolidation read/contribute checks. Release work must clear applicable integrity/packaging checks and report blocked or unsupported integrations honestly. [Release requirements](../specs/2026-10-06-release-and-integration-acceptance.md).

**Memory-quality pickup:** fix the relevant G183/G177 write-integrity gaps, repair G185’s reported test regression, then use [the first-memory-trial runbook](2026-10-06-first-memory-trial.md). Do a small trial before a full user-started drain. The immediate product question is whether asking ordinary questions about your life feels useful and trustworthy.

[Implementation review: every G ID](BACKLOG_IMPLEMENTATION_REVIEW.md) · [Active reasoning by priority](memory-evolution.md) · [Completed work](DONE.md) · [Reference context / original prompts](BACKLOG_CONTEXT.md) · [Working method](working-method.md) · [Cognition comparison](../research/2026-10-06-agent-memory-repo.md) · [Source/video gaps](../research/2026-10-06-source-refresh-and-video-gaps.md) · [Provider/source modularity](../specs/2026-10-06-provider-and-ingestion-modularity.md) · [Benchmark rebuild](../specs/2026-10-06-system-benchmark-rebuild.md)

## Current state and evidence

- **2026-10-09 — the entity card opens on its page (branch `perf/wiki-card`, owner request).** Measured on a synthetic owner page of the real one's size (5.6 MB, 5,921 claims, ~180 KB prose; `CardOpenProbeTests`, opt-in, scratch backend): the lag was the app drawing the page — `MarkdownBody` laid every prose line out at once, a 2.1–3.2 s main-thread stall on load and ~0.5 s per graph push while the page was shown — not the backend (`/entities` 0.1 s, decode 2 ms). Now `WikiArticle`/`WikiPageView` (rows built once off-main, drawn lazily, ~60 ms first screen, 0 stalls on pushes) and every other section behind a remembered disclosure that reads on open; the 6 MB claims list is read only when asked. Details in `docs/architecture/features.md` (the entity card).
- **2026-10-09 — page quality (G194, branch `fix/page-quality`, not merged).** Promotion is measured on the transcript (`promotion`), restatements fold (`fact_policy`), orientations no longer become "Undated background", the legacy synthesis path no longer drops the extraction's facts, a re-read makes no Stage 3 call, opt-in synthesis folds restatements in other words, Stage 1's prompt is rewritten around the person's relation. Owner decisions: synthesis on/off (numbers in the G194 row), archiving one-conversation pages below the bar, running `api.scripts.repair_page_quality` (dry run first) on the bank. Measure the prompt with a paired real-model pilot.
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
| 6 · P2 | App-free server package | G181/G187/G135/G92; Cursor engine G50/G49/G122 | Supported Linux/macOS install/service/upgrade path with one primary bank writer and client/remote smoke checks. Evaluate Windows native versus WSL separately. An existing Python backend is not a supported headless package. |
| 7 · P2 | Modular providers and ingestion in frontend/backend | G50/G49/G122; G188/G190/G126/G161; Cursor G76/G110 | Registered capabilities/small adapters drive setup/status/engine controls and source intake. Add/remove a fixture provider/source without unrelated core/view changes; preserve unavailable saved selections/history. Verify Cursor client versus engine capabilities separately. iMessage uses a minimal source/detector seam earlier; broader migration follows. [Requirements](../specs/2026-10-06-provider-and-ingestion-modularity.md). |
| 8 · P2 | Start prompts and portable skills | G73/G118/G113, G138/G178, G112/G55; G186 after CLI | Save/find/adapt reusable objective briefs with candidate status, original/variant provenance, project inputs and outcome evidence; copy/export across harnesses without requiring Sleep or skill compilation. See [start prompts](../specs/2026-10-06-start-prompts.md). Then verify catalog/BYO install, ground existing skills and compile standalone bundles; demonstrate schema-aware SQL reuse with R2 governance. Generate AMR export separately; external AMR import remains research. |
| 8b · P2 | Home revamp | G189 (b); G110/G137/G125 | The owner picks from 2–3 direction-D mockups of what Home shows first (projects in flight, what changed, what needs them) before any build. Do not rebuild the Ask field or inbox counts. |
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

Use a separate named real test bank or an explicitly chosen existing bank, with a recoverable committed baseline. New exports are imported normally; do not wipe the bank or mark every episode unprocessed to force a rerun. Inspect the import preview, preserve dates/speakers, then run a small batch with the selected engine. An API-funded run needs a budget; a user-started plan engine respects its plan limits and pause behavior. Scheduled plan use remains forbidden by ruling 4. Runbook details: [G10 trial](2026-10-06-first-memory-trial.md).

## Unstructured follow-ups retained from the old handoff

These are attached to permanent rows instead of becoming a second queue. Older disclosures require a current-code reproduction before implementation; do not re-open an audit fix from historical prose.

- **G106/G19:** confirm remaining client/backend ID sanitizer parity and wikilink navigation outside a WindowGroup.
- **G109:** graph physics phases/visual fit check; re-check historical WKWebView remount claims against the merged audit fixes.
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
12. **Plan usage and model prices show on the Sleep page's Details and its engine menu — and nowhere
    else yet (owner, 2026-09-28).** This supersedes the 2026-09-03 "prices and token usage are not
    shown anywhere in the app" ruling for those two surfaces only; ruling 4 (a scheduled cycle never
    spends plan quota) is untouched, and so is the no-cost-tiles, no-cost-per-day-chart half of the
    old ruling.

    What is shown, and why it is honest:
    - **Every figure carries its basis in words.** "Charged" is the provider's own bill (API key,
      OpenRouter). "At list price" is an estimate from the public price table or the Claude CLI's
      metering, never a charge. A plan cycle is its window's before → after.
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
    row and Details' Last cycle, never a price outside them — ruling 12) rather than prevented. Consequences built with
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
