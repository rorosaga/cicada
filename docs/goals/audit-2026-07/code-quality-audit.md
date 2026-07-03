# Cicada — Adversarial Code-Quality Audit: Final Report

Audit scope: full repo (api/, mcp/, app/, benchmarks/, scripts/, docs/, tooling). All findings below survived an independent verification pass against the actual code; severities reflect post-verification adjustments.

---

## 1. Overall Verdict

Cicada is in genuinely good shape for a solo-built capstone heading toward a downloadable product — the storage/git provenance layer is unusually well engineered (centralized markdown parsing, all git subprocess calls in one validated service), the benchmark tooling respects its own privacy rails exactly as documented, and no swallowed-assertion tests or fake coverage were found anywhere. The debt that exists is concentrated and characterizable: **three ship-relevant correctness risks** cluster around the MCP server (the primary deployment surface) and the LLM-call seam, and the dominant anti-pattern repo-wide is *"built but never wired"* (resolve_llm_fn, ABLATIONS, hub_kind, uploadMultipart, mcp_config.json) plus *"copy instead of extract"* (~25 confirmed DRY findings, several with measurable drift between copies). Nothing here is unshippable; a focused one-to-two-week hardening pass on the high/medium set below would clear the launch-blocking material, and most of the low-severity items fold naturally into the already-open G19 hygiene sweep.

---

## 2. Confirmed Findings (ranked by severity)

### HIGH

**H1. MCP tools silently read/write the wrong memory bank** — `mcp/server.py:223`
Evidence: `get_memory_path()` returns the raw memory root while `api/config.py` re-resolves the active bank via `banks.yaml` per request; all 9 MCP handlers bypass this, so after activating a second bank in the app, `cicada_save_episode` writes to the old bank forever, invisible to the active bank's Sleep cycle.
Fix: wrap `resolve_active_bank_path(root)` in a guarded `try/except → return root` inside `get_memory_path()` (fallback matches the registry's own legacy contract); add a test asserting bank-switch is honored. Longer term, route `save_episode` through the running backend like `handle_ask` already does.

**H2. One ordinary title aborts the entire nightly Sleep cycle** — `mcp/server.py:1046` + `api/services/sleep_cycle.py:349,405,424,439`
Evidence: `handle_save_episode` hand-rolls frontmatter via unescaped f-string — `title: Meeting: Q3 roadmap` is invalid YAML (reproduced with `yaml.safe_load`) — and sleep_cycle's loaders call `markdown_parser.parse` bare inside glob loops, so one malformed file stalls *all* pending episodes.
Fix: (a) build the frontmatter dict and call `markdown_parser.write()` (precedented: the same file already imports it at line 744); (b) wrap the four bare parse sites in try/except-log-skip, mirroring `claim_pipeline.py:64-68` — a skipped episode stays unprocessed and requeues. Add a regression test with a colon-title episode plus a corrupted sibling.

**H3. LLM-call seam is broken: `resolve_llm_fn` is dead while 6 call sites hand-roll litellm with inconsistent hang protection** — `api/services/providers.py:56`
Evidence: the factory (self-described "preferred seam going forward", carrying the OpenRouter attribution feature) has zero production callers; `entity_extractor`/`entity_resolver` carry proven hardening (reasoning-off, timeout, retry, lenient JSON) but `conflict_resolver.py:577/626` and `skill_extractor.py:76` have none — and both swallow exceptions, so Sleep Stages 3–4 silently no-op or hang up to litellm's 600s default per entity on the exact GLM behavior already documented as a past incident.
Fix: extract one shared `call_llm(...)` in providers.py built on `resolve_llm_fn` (must wrap **acompletion** — call sites are async — and support a text mode for `_synthesize_entity_update`); migrate skill_extractor/conflict_resolver first (zero protection today), then extractor/resolver/ask_service. Closes G19(e) by adoption and makes attribution headers actually reach calls.

### MEDIUM

**M1. Gemini exports silently mis-parse on the primary upload path** — `api/routers/conversations.py:25` (dry/bug)
Evidence: `upload_conversation` hand-rolls dispatch while the same file's `parse_export_bytes` (used only by banks.py) correctly detects Gemini Takeout and handles zips; a MyActivity.html upload via the app produces role-"unknown", timestamp-None episodes that the next Sleep cycle consolidates — silent memory pollution.
Fix: replace the inline dispatch with `parse_export_bytes(content, filename)`, re-key the label map on the returned format tags, update the `origin`-frontmatter comment at :703, optionally allow .zip in UploadOverlay.

**M2. Claim-layer decay archive tier is dead code** — `api/services/claim_reconciler.py:424`
Evidence: the `< archive_threshold` and `< nudge_threshold` branches emit byte-identical nudges; `archive_threshold` has zero observable effect. Works today only because the legacy entity path still runs — retiring it per G19(a) silently drops archiving entirely.
Fix: implement the spec'd page-level tier (distinct `archive_nudge` action, `status: decaying`, keep-or-archive question in inbox_generator) per sleep-trust-reconciliation.md §7 — do NOT auto-close claims (spec forbids it). Minimum: collapse the branches and leave a TODO referencing the spec.

**M3. WKWebView retain cycle leaks a web view on every Graph-tab revisit** — `app/.../Views/Graph/GraphView.swift:21`
Evidence: `userContentController.add(coordinator)` strongly retains the Coordinator, which strongly holds the webView, which owns that controller — closed cycle; zero `dismantleNSView`/`removeScriptMessageHandler` in the target, and ContentView rebuilds GraphView per tab switch. Unbounded gradual memory growth in a long-running app.
Fix: add `dismantleNSView` removing the "cicada" handler, and make `Coordinator.webView` weak (existing uses already handle nil). Verify with the Xcode memory graph.

**M4. conversations.py is a 738-line parsing library living in a router** — `api/routers/conversations.py:471`
Evidence: six format parsers plus episode staging inline; `banks.py:25` performs the tree's only router-to-router import, reaching into underscore-private `_stage_episodes`.
Fix: extract to `api/services/conversation_import.py`, rename `_stage_episodes` → `stage_episodes`, leave the router as a thin shim; update test imports.

**M5. mcp/server.py duplicates markdown_parser/id_utils on a contested premise, with an O(hops×N) hot-path scan** — `mcp/server.py:407,922,939`
Evidence: `_mcp_sanitize_id` is byte-identical to `id_utils.sanitize_id` (which is stdlib-only and safe to import); `_entity_id_for_name` re-reads and re-parses potentially all 1,882 entity files per call inside the recall wikilink loop.
Fix: import `sanitize_id` directly (free win); build a name index once per handler call; settle the interpreter story — register the MCP server with `api/.venv/bin/python` so the pyyaml-free fallback parsers can be retired, or explicitly document them as the deliberate degraded path and guard the currently-unguarded `api.*` imports in `handle_get_perspective`.

**M6. No conftest.py — six test-helper families copy-pasted across 2–5 files with confirmed drift** — `api/tests/` (anchor: `test_banks.py:139`)
Evidence: TestClient builder ×4, bag-of-words `fake_embed` ×4 (with a diverged zero-norm branch), git harness ×2, byte-identical `_make_entity` ×2, `run(coro)` shim ×5, memory-dir scaffolding ×4+.
Fix: add `api/tests/conftest.py` with an `api_client` fixture-factory (settings-cache clear on setup *and* teardown), `make_fake_embed(vocab, zero_norm=...)`, `git_repo`, and `make_entity`; migrate TestClient + fake_embed first, the rest opportunistically.

**M7. Entity-resolve-or-404 copy-pasted ×4, creating an inconsistent name-lookup gap** — `api/routers/entities.py:33,114,130,185`
Evidence: name/case-insensitive lookups succeed on `/context`/`/claims` but 404 on `/history`/`/diff`/`/location`; worse, on case-insensitive APFS a wrongly-cased id passes `Path.exists()` then silently yields empty git history (git paths are case-sensitive).
Fix: one `_resolve_entity_or_404` helper built on `id_utils.resolve_entity_id` (authoritative casing), and use the resolved id in all downstream git calls and responses.

**M8. Three hand-written multipart uploads; `uploadFile` byte-duplicates the helper written to replace it** — `app/.../Services/APIClient.swift:669` (also 375, 577)
Evidence: `uploadMultipart`'s own doc comment says both endpoints reuse it; neither does, and the copies have already drifted in decode-error behavior.
Fix: make `uploadMultipart<T: Decodable>` generic with uniform `APIError.decodingError` wrapping; reduce `uploadFile`/`importToBank` to one-liners; fix the stale comment.

**M9. Malformed markdown files silently vanish from five read surfaces** — `api/services/inbox_service.py:78` (+ entities.py:304/342/415, claims.py:73, search.py:30)
Evidence: bare `except Exception: continue` with zero logging around `markdown_parser.parse` — a hand-edited or LLM-corrupted file disappears from inbox, search, context, hubs, and claims with no diagnostic, contradicting the repo's own "transparency over magic" principle and its established `logger.warning` pattern in media_ingestor/link_enrichment.
Fix: six one-line changes — bind the exception, `logger.warning` filename + error, keep the skip behavior. Leave the documented LEANN degrade paths alone.

**M10. Top-bar + upload-overlay chrome copy-pasted verbatim into four screens** — `app/.../ContentView.swift:71` (+ SleepView, FeedView, TopicsView)
Evidence: SleepView's own comment admits the replication; drift already occurred (TopicsView is missing the overlay fade animation).
Fix: a `topBarAndUploadOverlay(selectedTab:onUploadDismissed:)` ViewModifier owning the `@State`; preserve SleepView/FeedView's on-dismiss refresh callbacks. Removes ~50 lines and the ×4 maintenance surface.

**M11. EntityDetailCard is a 921-line god view; ~10 direct `APIClient.shared` calls inside View structs** — `app/.../Views/Graph/EntityDetailCard.swift:754`
Evidence: 4-tab rendering + network calls + claim-divergence business logic in one file, against the app's own documented @Observable-ViewModel convention; TopicsView.swift:740 only `print`s a fetch failure.
Fix (narrowed): extract the pure claim derivations (`observerGroups`/`divergences`/`contestedKeys`) into a testable type and split the four tabs; add an UploadViewModel for UploadOverlay's 4-call state machine; surface the TopicsView error in UI. Leave the two self-contained leaf views (BeliefTimelineView, TranscludingMarkdownView) as-is — per-instance `.task` fetching is idiomatic there.

**M12. mcp/server.py: tool schemas and dispatcher are two hand-synced lists in a 1,122-line monolith** — `mcp/server.py:26,232`
Evidence: a schema entry with no matching `elif` fails only at call time; five responsibilities (RPC loop, dispatch, hub matching, inbox rendering, HTTP fallbacks) share one file with no boundaries.
Fix: Phase 1 — a single `TOOLS: dict[name, (schema, handler)]` registry; derive tools/list and dispatch from it. Phase 2 (optional) — split rpc/handlers into modules; note the `mcp` package name will shadow the official MCP SDK if ever installed.

**M13. Both embed resolvers triplicate all three embed-closure implementations** — `api/services/providers.py:181` (vs 273, 198 vs 317, 283-308 vs `_openrouter_embed_fn`)
Evidence: production-load-bearing on both build and query paths; the OpenRouter copy has no request timeout, and any hardening currently needs two edits per provider.
Fix: add a `model=` param to `_openrouter_embed_fn`; extract `_make_openai_embed_fn`/`_make_local_embed_fn`; existing hermetic tests are the safety net.

**M14. backfill_entity_pages.py silently discards git commit failures after mutating live memory** — `scripts/backfill_entity_pages.py:172`
Evidence: `git add`/`git commit` with `check=False`, no returncode inspection, unconditional exit 0 — and uncommitted edits get swept into the *next* Sleep commit with the wrong trigger and author: permanent provenance corruption in a provenance-first system.
Fix: porcelain-status check for the legitimate nothing-to-commit case, fail loudly otherwise; build the message via `git_service.build_commit_message(..., authors=["user"])` so the commit stops being attributed to "unknown".

**M15. Makefile ABLATIONS knob silently does nothing** — `Makefile:7`
Evidence: declared, never read; `make ablation ABLATIONS="default"` still runs all 5 configs — each a full LLM-cost sleep cycle.
Fix: `ABLATIONS ?=` empty default + `$(if $(ABLATIONS),--only $(ABLATIONS),)` on the run_ablation call (the `--only` flag already exists); document in `make help`.

### LOW

Compact format: *file:line — evidence → fix.*

- **L1.** `mcp/mcp_config.json:3` — stale template: wrong server key (`cicada-bookworm`), bare `python3`, placeholder paths; nothing reads it, and install.sh's `^cicada\b` idempotency grep matches it and would skip real registration → delete it (install.sh already prints correct fallback JSON); fix the stale companion-and-install.md references.
- **L2.** `mcp/server.py:837` — keyword-search +10/+5/+2 formula in 3 copies, already drifted (MCP scores `related` +3, api copies don't) → consolidate the two api-package copies into `api/services/keyword_search.py`; keep the MCP mirror as documented degraded path with a keep-in-sync comment.
- **L3.** `api/routers/search.py:44` (+ entities.py ×2, status.py) — SqliteVecIndexer lazy-import-degrade hand-rolled 4× (5th in sleep_cycle) → make vector_index read paths never raise; add `get_vector_indexer(...) -> SqliteVecIndexer | None`; fold into G19(c).
- **L4.** `api/services/inbox_service.py:28` — max-suffix+1 id algorithm ×5, `inbox_service.next_inbox_num` fully dead → one `next_numbered_suffix()` in id_utils; delete the dead copy.
- **L5.** `api/services/transclusion_resolver.py:38` — cross-module imports of `_one_line_summary`, `_CLAIMS_BLOCK_RE`, `_write_graph_edges` (a 4th consumer in media_ingestor) → rename to public / add `strip_claims_block()`; lift the function-local imports to module level.
- **L6.** `app/.../Views/Inbox/InboxListView.swift:103` — empty-state block reinvented 5× → promote FeedView's helper to a shared `EmptyStateView` + a compact `InlineEmptyState`; don't force all five through one signature.
- **L7.** `api/routers/banks.py:89` — HTTP status chosen by substring-matching exception text ("Unknown bank"/"already exists") → typed `BankNotFoundError`/`BankConflictError` subclassing ValueError; map in ordered except handlers; pin with two router tests.
- **L8.** `app/.../Models/Entity.swift:508` — backend `hub_kind` never decoded; graph.js has no consumer either, so it's a dropped design thread, not a runtime bug → either finish end-to-end (decode + forward + distinct hub visual, ~15 lines) or delete the wire field under G19.
- **L9.** `api/services/conflict_resolver.py:384` — `_compose_entity_body`/`_fallback_merge_body`/`_merge_history_entries` dead (~65 lines, superseded by entity_body v2) → delete all three as one unit.
- **L10.** `api/services/graph_builder.py:353` — graph_edges.yaml safe-load boilerplate actually ×6 across four modules, with drift (logging vs silent; one copy has a latent AttributeError on non-dict rows) → one `load_graph_edges()` returning `[]`, warning on parse failure.
- **L11.** `api/services/vector_index.py:290` — embed-and-rebuild block character-identical ×3 (+near-copy in `_rebuild_pending_index`) → `_embed_and_rebuild(kind, staged)` helper mirroring existing `_search_kind`.
- **L12.** `api/routers/banks.py:54` — BankListResponse rebuild block verbatim in all 5 endpoints → `_bank_list_response(root)` helper.
- **L13.** `api/services/entity_body.py:155` — `_merge_facts` ≡ `_merge_open_questions` → collapse to `_merge_bullets()`; leave `_merge_links`/`_merge_history_bullets` (genuinely different).
- **L14.** `api/services/inbox_service.py:104` — date helpers byte-duplicate conflict_resolver's, self-admitted in a "mirrors" comment → extract `date_utils.py` or fold into the G19(a) conflict_resolver retirement.
- **L15.** `mcp/server.py:280` — POST-to-backend urllib block ×2 → `_post_backend(path, payload, timeout) -> dict | None` + BACKEND_URL constant; keep handle_ask's normalization-failure fallback semantics.
- **L16.** `api/services/link_enrichment.py:222` — re-implements media_ingestor's HTTP fetch while importing its private constants, contradicting its own docstring → extract public `fetch_html(url, client)` in media_ingestor.
- **L17.** `app/.../EntityDetailCard.swift:365` + FeedView.swift:331 — identical "## Section" extraction loop and header-fallback list ×2 → one helper + `entity.mediaDescription` computed property.
- **L18.** `app/.../Common/ClaimChip.swift:177` — AuthorPill's comment claims shared styling with EntityDetailCard's history badge, which inlines a drifted copy → use `AuthorPill(entry.author)` (keep the isEmpty guard); fix the doc comment.
- **L19.** `app/.../Common/UploadOverlay.swift:332` — directory-walk-and-filter ×2 → `collectFiles(from:allowedExts:skippingFilenames:)`; note the users.json skip becomes uniform (call it out in the commit). Don't unify the per-file upload loops (purposeful divergence).
- **L20.** `app/.../Services/APIClient.swift:703` — request/validate/decode boilerplate ×4 (+multipart = 5), with real drift (post<T> throws raw DecodingError) → `send(_ request:) -> Data` + `makeJSONRequest`; uniform decodingError mapping.
- **L21.** `app/.../Resources/graph/graph.js:109` — webkit postMessage try/catch ×6, inconsistently silent → one `postToSwift(payload)` with a standalone-browser console fallback.
- **L22.** `app/.../EntityDetailCard.swift:884` — `renderedMarkdownAttributed` (~38 lines) dead; two stale comments reference it → delete; reword TranscludingMarkdownView.swift:6 and ClaimChip.swift:216. Ticks G19(h).
- **L23.** `app/.../ViewModels/GraphViewModel.swift:190` — `loadFullEntity` swallows errors with `print()`; note no view renders `errorMessage` either (even loadGraph's write is dead state) → add a per-detail failure signal + inline retry banner in EntityDetailCard; render or remove `errorMessage`.
- **L24.** `benchmarks/run_table3.py:223` + run_ablation.py:103 — identical run-sleep-and-detect-swallowed-failure block ×2 → `run_sleep_cycle_timed()` in workspace.py, keeping deferred api imports inside the helper body.
- **L25.** `benchmarks/run_table1.py:128` — record-build/write block ×3 with positional CSV rows that can silently misalign against CSV_HEADER → one `_emit(...)` helper deriving JSONL and CSV from the same values.
- **L26.** `memory_backup/`, `data/` — 20MB stale pre-migration snapshot + 208MB of raw personal exports at repo root, zero code references → delete memory_backup/ (memory/ is its own git repo); move data/ to the established external staging path; record under G19.
- **L27.** `scripts/backfill_entity_pages.py` vs `api/scripts/seed_claims.py` — maintenance CLIs split across two homes; backfill needs a sys.path hack to import api.services → move backfill into `api/scripts/`, delete the hack, update Makefile:59.
- **L28.** `docs/` — no top-level README; 33 of 52 files are a milestone journal indistinguishable from current specs → ~15-line docs/README.md mapping design/goals/inspiration; add the G19(g) superseded banner to d2-recommendation.md.

---

## 3. Uncertain / Judgment Calls

No findings were left unverified, but several fixes involve product decisions rather than clear-cut corrections:

- **MCP's pyyaml-free posture** (M5, L2): partially deliberate, inconsistently applied. Decide once whether the supported interpreter is `api/.venv/bin/python` (then delete the fallback parsers) or bare `python3` (then keep them, document them, and guard the currently-unguarded imports). Everything in mcp/server.py flows from this call.
- **Claim archive tier** (M2): the spec forbids decay from closing claims, so the "right" fix is the page-level `status: decaying` tier — nontrivial. Collapsing the branches with a TODO is an acceptable pre-ship stopgap, but only if G19(a)'s legacy-path retirement is gated on implementing it.
- **hub_kind** (L8): ship the type-hub/tag-hub visual or delete the wire field — either is fine; the current half-state is the only wrong answer.
- **G19(a) legacy conflict_resolver retirement** shapes how much to invest in M2, H3's conflict_resolver migration, and L14 — treat those as mechanical swaps, not redesigns, if retirement is near.
- **WKWebView leak severity** (M3): modern WebKit pools content processes, so the practical impact is gradual native/JS-heap memory growth, not a process-per-visit explosion. Still worth the 6-line fix.
- **Zip uploads on /conversations/upload** (M1): only direct API callers hit the 400 today (the app filters client-side); enabling .zip in the picker is optional.
- **Test fake_embed zero-norm drift** (M6): looks like deliberate per-test adaptation, not a bug — the conftest factory should expose it as a parameter rather than silently standardize.
- **The `mcp/` package name** shadows the official MCP SDK on PyPI if it's ever installed — rename to `cicada_mcp` if Phase-2 restructuring happens.

---

## 4. Top-5 Refactor Plan (prioritized)

**1. Harden the capture-to-Sleep spine (H1 + H2).** Fix `get_memory_path()` bank resolution, switch `handle_save_episode` to `markdown_parser.write()`, and wrap sleep_cycle's four bare parse sites in log-and-skip. Why first: these are the only findings where a normal user action silently corrupts or halts the core product loop (wrong-bank writes; one colon-title killing every nightly cycle). Effort: **~half a day** including regression tests. Do this before any release.

**2. Adopt the LLM seam (H3, + M13 alongside).** Build `call_llm()` on `resolve_llm_fn` (async, text mode), migrate skill_extractor and conflict_resolver first, then extractor/resolver/ask_service; dedupe the embed closures in the same file while you're there. Why second: Sleep Stages 3–4 currently have zero hang protection and swallow failures on the already-observed GLM failure mode — a multi-hour silent-degradation risk per nightly run — and this closes G19(e). Effort: **~1 day**, protected by existing extractor-robustness and provider tests.

**3. Extract the conversation-import service and fix the dispatch regression (M1 + M4).** Move the ~660 lines of parsing/staging into `api/services/conversation_import.py`, wire `parse_export_bytes` into `upload_conversation`. Why third: it fixes a real user-facing mis-parse (Gemini) and removes the repo's only architectural boundary violation in one mostly-mechanical move. Effort: **~half a day** (mostly import updates + label-map re-keying + test module paths).

**4. mcp/server.py Phase 1 (M5 + M12, sweeping in L2/L15 and L1).** Tool-registry dict replacing the hand-synced lists, import `sanitize_id` from id_utils, per-call name index for the wikilink hop loop, `_post_backend` helper, delete the stale mcp_config.json — and make the interpreter decision (Judgment Call #1) that unlocks deleting the fallback parsers later. Why fourth: MCP is the primary deployment surface and the roadmap keeps adding tools to this file; every future tool currently inherits the drift-prone structure. Effort: **~1 day**.

**5. Swift app hygiene pass (M3 + M8 + M10 + M11).** The 6-line WKWebView teardown first (real leak), then generic `uploadMultipart<T>`, the shared top-bar/overlay ViewModifier, and the EntityDetailCard slim-down (ClaimDerivations extraction + tab split + UploadViewModel). Why fifth: all real, none data-corrupting; batching them into one pass amortizes the build-and-verify cost of touching the app target. Effort: **1–2 days**, verified with the Xcode memory graph and a manual click-through.

**Everything else:** add `api/tests/conftest.py` (M6) and the six log-at-swallow-sites lines (M9) opportunistically as those files are touched — both are cheap and pay off immediately in debuggability; fold the remaining low-severity DRY/dead-code items (L4, L9–L13, L22, L26–L28, M14, M15) into the already-open G19 sweep so each removal is recorded against a tracked goal rather than done ad hoc.