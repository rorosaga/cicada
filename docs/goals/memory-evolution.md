# Goal: Memory Evolution (improvement wave)

Backlog distilled from Rodrigo's notes (2026-06-16). Triaged into three tracks:
**APPLY** (buildable now, low architecture risk), **RESEARCH** (needs investigation —
findings land in [`../inspiration/research/`](../inspiration/research/)), and **DECIDE**
(needs Rodrigo's call before work proceeds — see "Open decisions" at bottom).

Status legend: 🔲 todo · 🔬 researching · ❓ awaiting decision · 🛠️ in progress · ✅ done

**💸 spend flag:** items marked 💸 require **LLM API spend** (an OpenRouter/OpenAI key or a paid Sleep-cycle/dedup/rewrite run). Everything else builds and runs **key-free** (local embeddings for recall; the agentic `cicada-librarian` skill uses the user's *own* agent subscription, not a Cicada key).

Related: [`../inspiration/`](../inspiration/) (Honcho + gbrain analyses), [`../V2-ROADMAP.md`](../V2-ROADMAP.md).

---

## Implementation progress (branch `feat/memory-evolution`)

- ✅ **M1 — storage spine (D1):** LEANN replaced by `SqliteVecIndexer` (sqlite-vec,
  stored embeddings, derived/rebuildable). Entities + episodes + pending all ported;
  all consumers rewired (sleep_cycle, entity_resolver, routers, mcp). **EmbeddingGemma-300M**
  (768-dim, gated — HF auth done) is the default on-device backend, off the OpenAI API;
  asymmetric query/document prompts; model+dim recorded in the index. Verified end-to-end
  on real `memory/` (e.g. *"company I interned at"* → amazon). 7 tests green.
  - *Remaining cleanup:* remove `leann` dependency + delete `leann_indexer.py`; consider
    a one-off full reindex of the live 1,882-entity graph (~10–15 min CPU).
- ✅ **M2 — `ask_memory` endpoint (D3=BOTH):** `POST /ask` + `api/services/ask_service.py`
  (`answer_query(memory_path, query, top_k, *, retrieve_fn=None, llm_fn=None)`). Auditable
  synthesis: a grounded NL answer with **entity-level citations** (id, name, file_path,
  snippet, source_episodes) and explicit **gap analysis** (honest "I don't have information
  about X" — folds in A5). Empty/low retrieval => honest gap answer, low confidence, **no
  LLM call, no hallucination**. Retrieval defaults to `SqliteVecIndexer.search_entities`,
  synthesis to litellm JSON-mode per `Settings`; both injectable for hermetic tests.
  `cicada_ask` MCP tool wraps it (prefers running backend, degrades to the service direct).
  Hardened after adversarial review: `used_entities`/`citations` now agree (report the
  model's actual selection, not the full retrieved set); an answer citing only hallucinated
  ids degrades to a gap (no fabricated provenance); list-shaped LLM fields coerced so a bare
  string is not shredded into per-character gaps; empty/whitespace query short-circuits
  before any retrieval/LLM call; cold-index-on-populated-graph falls back to a disk substring
  scan (mirrors `routers/search.py`) instead of a false "I don't know"; `top_k` bounded
  `[1,50]` at the schema. 14 TDD tests (`api/tests/test_ask_service.py`); full suite 21 green.
  - *Known limitation:* `confidence` is the model's self-report (prompt-instructed to lower
    it on thin evidence); it is clamped to `[0,1]` but not coupled to a retrieval-score floor.
  - *Follow-up (nice-to-have):* line-level git-blame citations (entity-level shipped);
    retrieval-score-coupled confidence ceiling; request-time top_k tuning + answer caching.
- ✅ **M3 — git-provenance attribution + diffs (A1 + A2):** three cohesive pieces on top
  of the existing markdown+git provenance spine.
  - **Part A (M1 cleanup):** deleted dead `api/services/leann_indexer.py` and removed the
    `leann` dependency (`uv remove leann` → `uv.lock` updated; large transitive tree pruned).
    Proved zero importers first; the only remaining `leann` strings are intentional naming in
    `status.py`/`vector_index.py` docstrings, not imports.
  - **Part B (A2 — contributors / audit):** **commit-author trailer scheme** — every Cicada
    write appends one or more `Cicada-Author:` git trailers to the commit body. The author is a
    **model id** (e.g. `gpt-5.4-mini`, plus the disambiguation model when distinct) for
    sleep-cycle/agent writes, or **`user`** for manual/companion-app/media-save writes; legacy
    untrailered commits attribute to **`unknown`**. The trailer is appended after a blank line
    (git-trailer convention), carries no entity id, and is therefore **inert to the existing
    entity-line parsing** (`_infer_change_type`/`_build_description` round-trip verified).
    Producers wired: `sleep_cycle._finalize` (main + disambiguation models from `Settings`),
    `git_service.commit_resolution` (inbox/companion → `user`), `media_ingestor._commit_media`
    (`user`). Builder + parser live in `git_service` (`build_commit_message`, `_parse_authors`).
    New `GET /contributors` (`routers/contributors.py`) → per-author commit/file/entity counts
    + `last_active`, parsed repo-wide from trailers. Schemas: `Contributor`,
    `ContributorsResponse`.
  - **Part C (A1 — per-commit diff):** `GET /entities/{id}/history?include_diff=true` inlines a
    bounded added/removed diff per commit (opt-in so the default response stays small), plus a
    dedicated `GET /entities/{id}/history/{commit}/diff`. Each history entry now also carries
    `author` + `commit_hash` (per-entity attribution, A2). Schema: `EntityDiff`; extended
    `EntityHistoryEntry`.
  - **Security/robustness hardening (post-review):** the public diff endpoint validates
    `commit_hash` against `^[0-9a-fA-F]{7,40}$` (`_COMMIT_HASH_RE`) and passes `--end-of-options`
    before handing it to `git show`, closing an arg-injection / arbitrary-file-write vector
    (a flag-like `--output=...` hash). The diff is **actually bounded** now: `DIFF_MAX_LINES`
    (400/side) cap + a truncation marker + an `EntityDiff.truncated` flag — the schema comment
    no longer claims an unenforced bound. `_run_git` decodes with `errors="replace"` so a
    non-UTF-8 entity file degrades instead of 500ing; `get_sleep_history` gained `--root` so the
    initial commit lists its files (parity with `get_contributors`).
  - **Tests:** 20 hermetic TDD tests in `api/tests/test_contributors.py` (throwaway git repo
    with hand-crafted trailers; never touches live `memory/`): contributor aggregation
    (model vs `user` vs `unknown`), per-entity authoring model, per-commit diff content,
    non-git-dir + missing-commit graceful empties, router wiring, plus the post-review cases
    (flag-like/non-hex hash rejection with no file write, diff bounding/truncation,
    non-UTF-8 graceful path, root-commit file listing). Full suite **41 green**.
  - **SwiftUI (NOT build-verified — needs Xcode):** `APIClient` methods (`fetchContributors`,
    `fetchEntityHistory(includeDiff:)`, `fetchEntityCommitDiff`); models (`EntityDiff`,
    `Contributor`, `ContributorsResponse`, extended `EntityHistoryEntry`); a new
    `ContributorsView` + `ContributorsViewModel`; author badge + inline diff in the
    `EntityDetailCard` history tab. The `ContributorsView` is **not wired into sidebar nav** yet.
    `EntityDiff` gained a `truncated` flag (decoded with `decodeIfPresent`, robust to old
    backends) and `fetchEntityCommitDiff` now percent-encodes the commit hash for consistency.

- ✅ **M4 — media feed + RSS connector + ingestion bookworm (R6 RSS half + G3 + §3.1/§3.4):**
  three pieces built on the existing media-ingestion engine — no new consolidation code.
  - **RSS/Atom connector (R6):** `media_ingestor.parse_rss(xml)` (stdlib `xml.etree`,
    namespace-tolerant, handles RSS `channel/item` + Atom `entry`, prefers Atom
    `rel="alternate"` links, `category`→tags, `content:encoded`/`description`/`summary`→note,
    skips link-less entries, returns `[]` on malformed XML). A feed is just another producer
    of `RawItem`s — it flows through the **existing** `_dedup_items` → `ingest_batch` →
    url_index/episode/entity path; Sleep Stage 5.55 (`inject_media_edges`) wires the resulting
    `media` entities unchanged. Thin `ingest_feed(xml, …)` convenience. `parse_upload` now also
    dispatches `.xml`/`.rss`/`.atom` (source label "RSS Feed") so dropping a feed file in the
    upload UI just works. **No new `rss` media_type** — reuses `url`/`youtube` via `_classify`
    so graph colors/filters are untouched. New `POST /sources/rss` (body
    `SourceRssRequest{feedXml?, feedUrl?, tags}`): `feedXml` ingests inline (keyless, offline);
    `feedUrl` is gated behind `CICADA_ALLOW_FEED_FETCH=1` (network off by default, never hit in
    tests). Reuses the `SourceUploadResponse` envelope.
  - **Relevance-sorted feed (§3.4 / G3):** `media_ingestor.compute_relevance(fm)` =
    `confidence × recency_decay × personal_weight`, clamped to `[0,1]`, where
    `recency_decay = exp(-decay_rate × weeks_since_last_referenced)` (mirrors the graph's
    temporal-decay model) and `personal_weight = personal_relevance_weight` (new **optional**
    frontmatter field, default 1.0; a `personal_relevance` note string is also read-if-present).
    `GET /sources` now computes `relevance` per item and takes `?sort=relevance|recent`
    (default `recent` for back-compat). `MediaSourceItem` gained `relevance` + `personalRelevance`.
    No second `/feed` endpoint — the existing `list_sources` body was reused.
  - **Ingestion bookworm (§3.1 / A3):** new reusable `Views/Common/BookwormView.swift` — a pure
    SwiftUI view that animates `BookwormSprites.frames(for:)` via a `Timer` (torn down on
    `onDisappear`), rendered through the proven `BookwormRenderer.image(grid:…)` primitive
    (the same one `InboxListView`'s empty state uses statically). Dropped into
    `UploadOverlay` replacing the static SF-symbol: it chews (`.digesting`) while ingesting,
    beams (`.happy`) on success, idles (`.awake`) otherwise — the **same** mascot as the menu bar.
  - **SwiftUI feed view (build-verified):** new `Views/Feed/FeedView.swift` +
    `ViewModels/FeedViewModel.swift` (`@Observable`, `fetchSources(sort:)`), a `Feed` sidebar tab
    (`AppTab.feed`, icon `photo.stack`) + `ContentView` branch. Rows show thumbnail (`AsyncImage`),
    title, media-type chip (`mediaPink`), site, and a relevance %; click opens the URL.
    `APIClient` gained `fetchSources(sort:)` (404→`[]`) + `ingestRSS(feedXml:)`; new
    `MediaFeedItem`/`SourceListResponse` Codable models.
  - **Tests:** 24 hermetic TDD tests in `api/tests/test_sources.py` (tmp dirs, inline fixture
    XML, enrichment monkeypatched to the offline fallback so **no network**): `parse_rss`
    (RSS/Atom/fields/YouTube-canonicalization/dedup/malformed), `parse_upload` feed dispatch,
    end-to-end `ingest_feed` create + idx-dedup + in-batch-dedup, `compute_relevance`
    (freshness/age/personal-weight/clamp/missing-fields),
    `POST /sources/rss` + `GET /sources?sort=` via `TestClient`, plus backfill for
    `normalize_url`/`url_hash`/`parse_netscape_bookmarks`.
    Full suite **65 green** (was 41). `swift build` → `Build complete!` exit 0.
  - **Post-review hardening (2 MUST-FIX + 1 wiring gap):** two independent adversarial reviews
    converged on the same blockers, all now fixed TDD-first:
    - **Unbounded RSS batch (robustness MUST-FIX):** `POST /sources/rss` now enforces the same
      `MAX_BATCH` (2000) 413 guard `/sources/upload` has, so a large/malicious feed can't trigger
      N enrichment fetches + 2N writes + a commit inline (`test_post_rss_rejects_oversized_feed`).
    - **`site`/`channel` always `null` on the wire (correctness MUST-FIX):** `list_sources` now
      reads `media.site`/`media.channel` back out of the entity frontmatter (they live there, not
      in `url_index.json`), so the Swift `FeedRow` site line and the site-search filter — previously
      permanently inert — actually receive data (`test_get_sources_populates_site_from_frontmatter`).
    - **RSS connector unreachable from the app (UX MUST-FIX):** the "Saved media" upload overlay's
      file picker (`allowedContentTypes`) and drag-drop filter (`allowedExts`) now accept
      `.xml`/`.rss`/`.atom`, which `parse_upload` already routes to `parse_rss`. Dropping/choosing a
      feed file now ingests through the existing upload path, making the `FeedView` "…or add an RSS
      feed" empty-state copy truthful. (Swift `swift build` re-verified, exit 0.)
    Full suite now **67 green**.
  - **Deferred:** **G2** (full media-type taxonomy expansion — research-paper/recipe/song/etc.)
    stays gated by D2 — left as a labeled TODO. Live `feedUrl` network fetch is implemented but
    flag-gated and untested (offline-by-design). Setting `personal_relevance`/`_weight` from the
    app (the §3.2 write path) is read-only for now. A dedicated **paste-feed-XML field** (vs.
    the file-drop path now wired) and routing the `/sources/rss` endpoint through `ingest_feed`
    to retire the test-only wrapper (review optional #4) are left as small follow-ups.

- ✅ **M5a — claim-layer foundation (in-page claims + derived index; $0 LLM, additive, reversible):**
  the store-format + parser + derived index foundation from the D2 ADDENDUM
  (`docs/goals/d2-architecture-final.md`) — editable pages are the source of truth, claims live
  **in** the page, the index is **derived**. Deliberately narrow: **not** wired into `/ask`, MCP, or
  the Sleep cycle yet (later milestones).
  - **`Claim` schema (`api/services/claims.py`):** dataclass with the full field set —
    `id, text, subject, predicate, object, object_kind, observer, context, epistemic, source_trust,
    confidence, valid_from, valid_to, superseded_by, supersedes, recorded_at, source_episodes,
    premises, authored_by, origin` (origin = G9 harness provenance, distinct from M3 `authored_by`).
    Sensible defaults so a minimal `Claim(id=..., text=...)` is valid (`observer=agent`,
    `context=general`, `epistemic=explicit`, `source_trust=agent_extracted`, `object_kind=node`,
    `confidence=0.5`, `valid_to=None`). `to_dict`/`from_dict` round-trip; `from_dict` tolerates sparse
    YAML records (legacy/partial).
  - **In-page block parser/writer (`api/services/claims.py`):** `parse_claims(body) -> list[Claim]`
    finds the fenced ` ```claims ` YAML-**list** block, parses each mapping into a `Claim`; returns
    `[]` for a legacy page (no fence), a malformed block (warn + `[]`, never raises), or a non-list
    payload. `write_claims(body, claims) -> body` inserts/replaces the block **in place** while
    preserving **all** surrounding prose verbatim (load-bearing: pages stay editable Wikipedia-like
    docs; the claims block is the co-located machine layer). Empty list still emits a visible `[]`
    fence. Round-trip invariant `parse_claims(write_claims(body, claims)) == claims`; exactly one fence
    after repeated writes.
  - **Derived `claims` index kind (`api/services/vector_index.py`):** `index_claims()` walks
    `entities/*.md`, `parse_claims` each, indexes **only currently-valid** claims (`valid_to is None`),
    embed = `claim.text`, metadata = `{claim_id, subject, predicate, object, observer, context,
    epistemic, source_trust, confidence, valid_from, superseded_by, origin, file_path}` — via the
    existing `_rebuild_table`/`_knn` machinery (records model/dim like the other kinds).
    `search_claims(query, top_k, *, observer=None, context=None, include_superseded=False)`: KNN over
    the `claims` kind, post-filters on `observer`/`context` when given, excludes `superseded_by`-marked
    claims by default, graceful `[]` on a missing db/kind (mirrors `search_entities`/`_search_kind`).
  - **Scaffolded M5 paths (`api/main.py`, no logic yet):** subdir-creation now also makes
    `candidates/` and `_procedures/`, and seeds `_predicates.yaml` (`{}`) + `_preferences.md` (a
    human-authored, never-clobbered stub) if missing — matching the existing pattern.
  - **Tests:** 16 hermetic TDD tests in `api/tests/test_claims.py` (deterministic bag-of-words
    `embed_fn` injected — no real models/network): Claim defaults + `to_dict`/`from_dict` round-trip +
    sparse tolerance; parse/write round-trip preserving surrounding prose; legacy page → `[]`; malformed
    + non-list fence → `[]` graceful; block replace-not-duplicate; `index_claims` valid-only filtering;
    `search_claims` observer/context post-filter + superseded exclusion; missing-index `[]`; model/dim
    recorded. Full suite **83 green** (was 67).
  - **M5a review fixes (TDD, $0 LLM):** two robustness MUST-FIX bugs on the first-class human-edit
    path closed, each with a failing-test-first regression. (1) **CRLF closing fence** — the closing
    `` ``` `` fence regex didn't tolerate `\r`, so a page saved/synced with CRLF line endings (Windows /
    `git autocrlf` / cross-harness sync per the ADDENDUM) parsed to `[]` and silently vanished from the
    derived index; fixed by allowing `\r?` before the close, with a CRLF round-trip test. (2) **Stale
    orphan fence** — `write_claims` on a page that already had two ` ```claims ` blocks rewrote only the
    first and left the second behind; now it replaces the first in place and strips any remaining
    fences, guaranteeing exactly one fence regardless of input. Also closed a test gap: added an explicit
    missing-`claims`-**table** (vs missing-db) `search_claims` → `[]` test. Full suite **86 green**.
    Deferred (non-blocking, agreed by both reviewers): `search_claims` `top_k*3` over-fetch starvation
    (pre-existing parity with `search_entities`, acceptable at personal scale); doc-example fence
    collision (inherent to in-page fenced blocks, flagged for M5b when real pages author format docs).
  - **Deferred (later M5 milestones):** wiring claims into `/ask` (claim-first retrieval), MCP
    `get_perspective`, and the Sleep cycle (Stage-1 claim extraction, Stage-3 mechanical
    invalidate-and-supersede, Stage-5 card render); deterministic `graph_edges.yaml` → seed-claim
    backfill (M5b); the app surfaces (M5c) and big-model extraction (M5d/G10).
- ✅ **M5e — claim/trust/retrieval core wired into Sleep + retrieval (TDD, $0 LLM, hermetic, additive):**
  the claim layer is now load-bearing in consolidation and retrieval. Built on `feat/memory-evolution`,
  41 new tests, full suite **185 green** (no real embed/LLM in tests — fake `embed_fn`, injected `llm_fn`).
  - **Predicate normalization + cardinality:** `predicates.build_cardinality_fn` / `is_single_valued`
    read the seed's `single_valued` / `multi_valued` lists from `<memory>/_predicates.yaml`; unseen
    predicate ⇒ **conservative multi-valued (coexist)** so Stage 3 never auto-closes on an uncertain
    cardinality. The runtime map is installed (idempotent, non-clobbering) at the top of `sleep_cycle.run`.
  - **Stage 1 — claim emission + origin:** `entity_extractor.entities_to_claims` deterministically projects
    the existing entity/relationship extraction shape (the back-compatible `observer=agent · context=general
    · epistemic=explicit · source_trust=agent_extracted` special case) into perspectival `Claim`s, with
    `origin` propagated episode→claim (`_derive_origin` maps legacy `source` → G9 harness id) and the raw
    predicate label carried on `predicate_raw` for the audit nudge.
  - **Stage 3 — trust-reconciliation (THE CORE), `claim_reconciler.reconcile_stage3`:** collides only on the
    mechanical key `K = (subject, predicate, context, observer)`; trust-gated, never recency-alone. The
    `trust_decision` table encodes `sleep-trust-reconciliation.md` §3 exactly — **no `agent_extracted` /
    `agent_reflected` / `external` claim can ever `SUPERSEDE` a human (`is_human` = `user_stated` **and**
    origin ∈ {manual_edit, clarification}, §6 origin-gated)**: it `COEXIST_FLAG`s (records the agent belief,
    keeps the human claim open + authoritative, emits a soft `divergence_nudge`) or `CONFLICT_NUDGE`s. Only
    **human-over-human with newer `valid_from`** closes a human claim; **agent-over-agent** on a single-valued
    key is mechanical invalidate-and-supersede (`valid_to`/`superseded_by`/`supersedes`, nothing deleted);
    multi-valued predicates coexist; `agent_reflected` may not close `agent_extracted` (`REJECT`, audited).
    Per-epistemic × source_trust **decay** runs here (lowers `confidence` only; never closes; `user_stated`
    fades 0.3×). Mandatory `normalization_audit` nudge on every auto-folded predicate.
  - **Stage 5 — section-aware merge + valid-only edges + index:** `entity_body.merge_sections_human_safe`
    is additive-only on human-edited pages (non-canonical / `human_edited` sections preserved verbatim — the
    prose mirror of rule 3a); `graph_builder.regenerate_edges_from_claims` rewrites `graph_edges.yaml` as a
    valid-only projection tagged with observer/context/claim_id (no-op when a bank has no claims, so seeded
    edge graphs aren't wiped); the derived `claims` index is rebuilt in the Stage-5 index pass.
  - **Retrieval swap:** `ask_service.build_claim_first_retrieve_fn` is the new default `retrieve_fn` —
    KNN over the `claims` index, claim→subject-entity mapping (citations point at `claim_id` + valid-window
    + observer), 1-hop object-neighbour expansion — with a **graceful `search_entities` fallback when the
    bank has no claims**, so `/ask` never regresses on un-consolidated banks. Contract
    (`answer/confidence/citations/gaps`) unchanged.
  - **MCP `cicada_get_perspective(subject, observer?, context?)`:** returns a subject's currently-valid
    (open, non-superseded) claims filtered by perspective, each rendered with its provenance — the D2
    Bookworm "who-believes-what" tool.
  - ✅ **Done in M5f (Stage 5.57):** the link-enrichment subagent (John → recommended websites). See
    the M5f entry below.
  - **M5e adversarial-review MUST-FIX pass (TDD, hermetic, +6 tests, full suite 191 green):** two real
    data-loss bugs found by review were fixed failing-test-first; the over-stated framing was corrected.
    - **(1) Live Stage-5 could overwrite human prose.** `conflict_resolver.apply_changes` ran the LLM
      synthesis path *unconditionally* and replaced page sections wholesale with the synthesized body
      (else bare `merge_sections_fallback`, no human gate), so a hand-edited Summary on a real page could
      be silently regenerated away — the prose-level violation of rule 3a. Fixed: a new `_is_human_edited`
      detector (frontmatter `human_edited: true` OR a non-canonical hand-added H2, evaluated on the RAW
      body *before* the lossy v2 lift folds such headings into Key Facts) now gates the path. Human-edited
      pages take the **additive-only** `merge_sections_human_safe` over their raw sections (every human
      line preserved verbatim, synthesis rewrite suppressed); agent-only pages keep full synthesis/merge
      behavior. Covered by `test_conflict_resolver_human_safe.py` (human-edited Summary not overwritten,
      non-canonical section survives, agent-only still synthesizes/merges).
    - **(2) Latent graph-edge wipe in Stage 5.7.** `regenerate_edges_from_claims` rewrote
      `graph_edges.yaml` *wholesale* the moment any page carried a claim, clobbering the relationship /
      wikilink-`mentions` / media-`about` edges written earlier in the *same* cycle (Stage 5/5.5/5.55) —
      a silent destruction of the non-claim graph the first time M5b seeding + a Sleep cycle ran on live
      memory. Fixed: the regen now **merges** — it preserves every non-claim edge (rows without a
      `claim_id`, the only rows this function owns) and replaces only the claim-derived rows. Covered by
      `test_claim_edge_regen.py` mixed-state + stale-claim-edge cases.
    - **Scope correction (resolved in M5f).** The M5e commit subject ("wire claim layer into Sleep")
      over-stated the consolidation half: `reconcile_stage3` / `entities_to_claims` were load-bearing in
      **retrieval** but not yet in the **live consolidation** Stage-3/5 (which still ran the legacy
      `resolve_and_prune` + M5b seeder). **M5f closes this** (below): the claim pipeline now runs inside
      the live cycle alongside the legacy entity path, so the human-protection invariant holds at the
      **claim** level in consolidation too — not just at the prose level (M5e fix 1).

- ✅ **M5f — claim layer made LOAD-BEARING in the live Sleep cycle (TDD, hermetic, $0 LLM, ADDITIVE):**
  the M5e claim core (`entities_to_claims` / `reconcile_stage3` / `write_claims` / `merge_sections_human_safe`
  / `regenerate_edges_from_claims`) now runs *inside* `sleep_cycle.run` on every cycle, layered **on top of**
  the unchanged legacy entity-extraction + `conflict_resolver` path (baseline never regressed). Built on
  `feat/memory-evolution`; **+18 tests, full suite 221 green** (LLM/embedding/git boundaries faked; no
  network, no real model in any test).
  - **New seam — `api/services/claim_pipeline.py` :: `run_claim_pipeline(extracted, existing, memory_path,
    settings, *, now_date=None, extra_claims=None)`:** one additive call that (Stage 1) projects the
    extraction output into agent-extracted `Claim`s via `entities_to_claims`, (Stage 3) reconciles them
    against the existing in-page ` ```claims ` blocks via `reconcile_stage3` (trust-gated, mechanical), and
    (Stage 5) writes the reconciled claims back into each entity page via `write_claims` — **preserving all
    surrounding human prose verbatim**. Subjects without a page yet are skipped (the promotion model owns
    page creation; never raises). `extra_claims` is the manual-edit/clarification injection seam
    (`user_stated` + human origin).
  - **Wired as Stage 5.56 in `sleep_cycle.run`** — *after* the entity path's Stage-5 page writes (so
    create-pages exist to host the claims block) and 5.55 media edges, *before* 5.6/5.7/index (so the hub,
    claim-edge and claims-index steps project the freshly-written claims). The whole stage is in a
    `try/except` so it can never hard-block the cycle.
  - **Trust invariant enforced END-TO-END in the live cycle**, proven by a real `sleep_cycle.run`
    integration test (`test_sleep_cycle_claims_wired.py`): a pre-existing human `works-at` claim on a page
    is **not** closed by a contradicting agent extraction in the wired cycle — it stays open + authoritative
    and a soft `divergence_nudge` lands in the inbox. (Plus `test_claim_pipeline.py`: agent-can't-supersede,
    human-over-human supersede, human prose survival, additive frontmatter, merged claim edges.)
  - **Claim nudges fold into the inbox — `inbox_generator.write_claim_nudges`:** turns the Stage-3
    `conflict_nudge` / `divergence_nudge` / `normalization_audit` / `decay_nudge` records into companion-app
    inbox items, reusing the same `inbox-NNN` allocator so they never collide with the legacy entity-path
    nudges written earlier in Stage 5.
  - **Stage 5.57 — link-enrichment (`api/services/link_enrichment.py`) shipped (the John→websites design):**
    `enrich_media_links(memory_path, changes, settings, *, summarize_fn=...)` scans `media` entities for
    thin/absent descriptions and records a `describes` claim, plus a `recommends` claim on any **person who
    shares the media's source episode**, with **bidirectional `![[…]]` transclusion** (John's page embeds the
    site, the site embeds John). Two paths: **§2a reuse (zero-LLM, default)** promotes a substantive on-page
    `## Description` straight into a claim; **§2b scour+summarize** is a single bounded mini-model call behind
    the injectable `summarize_fn` seam (`default_summarize` does the live fetch+LLM via `media_ingestor`'s
    HTTP helpers — offline-safe, capped at `link_enrich_max_per_cycle`). Idempotent via
    `enrichment_attempted`; YouTube/Instagram excluded; `link_enrich_enabled=False` is a clean kill switch.
    New `Settings`: `link_enrich_enabled` / `link_enrich_max_per_cycle` / `link_enrich_min_desc_len` /
    `link_enrich_excerpt_chars`. Covered hermetically by `test_link_enrichment.py` (reuse path, recommends +
    transclusion, idempotency, kill switch, injected summarizer, no-media no-op).

- ✅ **G15 — contributor avatars / visual identity (TDD backend + build-verified Swift, additive,
  backward-compatible):** each contributor on M3's `/contributors` view gets a GitHub-repo-contributors-style
  identity. Built on `feat/memory-evolution`; **+12 backend tests, full suite 233 green** (no network/model
  in tests); `swift build` exit 0.
  - **Schema (`Contributor`, camelCase wire):** three additive, defaulted fields so the wire stays
    backward-compatible — `kind` ("user" | "model" | "unknown"), `provider` ("openai" | "anthropic" |
    "google" | "other" | null), `avatar_url` (string | null).
  - **Derivation (`git_service`):** `_classify_author_kind` (`user`→user, `unknown`→unknown, else model);
    `_provider_for_model` (lower-cased: distinctive markers `gpt`/`text-embedding`→openai,
    `claude`→anthropic, `gemini`/`gemma`→google as substrings; the short OpenAI o-series `o1`/`o3` match
    only as an **anchored token** — whole id / prefix / `[/-]`-delimited — so ids like `macro1`/`retro3`
    don't false-positive as openai; else `other`; null for user/unknown); `avatar_url` for the
    `user` author = `https://github.com/<handle>.png` where `<handle>` comes from the new optional
    `Settings.github_user` (`CICADA_GITHUB_USER`), else the repo's `git remote get-url origin` GitHub path
    (`_github_handle_from_remote_url` handles both https + `git@` ssh forms), else null — derived safely
    (a missing remote / non-git / non-GitHub origin all degrade to null, never crash). The origin lookup
    only fires when there's actually a `user` contributor to show.
  - **Frontend (`ContributorsView` / `Contributor` model):** Swift model extended with the optional fields
    (`decodeIfPresent`, so it still decodes against an old backend). A new `ContributorAvatar` renders per
    row: `user` → `AsyncImage(url: avatarUrl)` rounded (fallback `person.crop.circle.fill`); `model` → a
    provider badge (colored circle + 1-letter monogram, brand-ish per-provider colors, neutral for "other");
    `unknown` → `questionmark.circle.fill` muted. Row classifies via the backend `kind` with an
    author-string fallback for old backends.
- ✅ **M5-prep — provider factory + OpenRouter + model-comparison harness (TDD, hermetic, additive):**
  groundwork for G10 (big-model bulk re-extraction) so the consolidation model can be pointed at any
  provider OpenRouter routes. New **`api/services/providers.py`** with two pure factories:
  `resolve_llm_fn(settings, *, model=None, completion=None)` (resolves a model spec → a callable bound to
  that model id; litellm already routes `openrouter/<id>`/`openai/…`/`anthropic/…`/`gemini/…` purely from
  the prefix, so **OpenRouter needs zero special-casing** beyond opt-in `HTTP-Referer`/`X-OpenRouter-Title`
  attribution headers added only when the model starts with `openrouter/`), and
  `resolve_embed_fn(settings, *, transport=…)` (folds the old `vector_index._resolve_embed_fn` body —
  now a one-line shim — and adds a third `CICADA_EMBEDDING_MODE=openrouter` branch: POST
  `https://openrouter.ai/api/v1/embeddings`, default `google/gemini-embedding-2`, **dim recorded live from
  the response**, openai-style auto-degrade to local when `OPENROUTER_API_KEY` is missing). Config additions
  are all defaulted to today's behavior — `consolidation_model=""` (→ `effective_consolidation_model` falls
  back to `litellm_model`), `embedding_model_openrouter`, `openrouter_referer/title` — so an unconfigured
  install is byte-identical. TDD'd hermetically in `api/tests/test_providers.py` (16 tests, injected fake
  `completion`/transport/factories; **no network**); full suite **254 green** (238 prior + 16). Plus the RUN
  harness **`benchmarks/run_model_comparison.py`** — reuses the real `entity_extractor.extract` Stage-1 path
  per model on the biggest-N real episodes, writing side-by-side
  `benchmark_results/model_comparison/<episode>/<model>.json` (entities, relationships, claims via
  `entities_to_claims`, summaries, `usage{tokens,cost}` from the litellm response) + an `index.md` table,
  bounded by `--models`/`--n`/`--max-chars`, with `--embed-test` for live dim/cost on the embedding model.
  `benchmark_results/` is gitignored — never committed. → feeds **G10**; relates to **D2/M5d** (big-model
  re-consolidation) and **M3** (`Cicada-Author` provider attribution).
- ✅ **2026-07-13 — Calendar ICS + Apple Notes connectors (R6 deferred half, backend):** two more
  one-way, keyless episode emitters, mirroring `feed_registry`/`bookmark_sync` exactly. **Calendar:**
  `api/services/calendar_registry.py` — `<memory>/calendars.yaml` subscription registry (`webcal://`
  normalized to `https://` at subscribe time, same dedup/tag-merge shape as feeds), `icalendar`-backed
  `parse_ics` (line folding + TZID resolved, date-only all-day events, RRULE presence noted but not
  expanded) filtered to a past-30-day/next-180-day window, one episode per `VEVENT`
  (`origin: "calendar"`), dedup on UID+DTSTART(+SEQUENCE) via `memory/sources/calendar_index.json` so an
  edited event re-ingests but an unchanged one never duplicates; polling gated behind the same
  `CICADA_ALLOW_FEED_FETCH=1`. **Apple Notes:** `api/services/notes_sync.py` — one batched `osascript`
  call (never per-note) dumps every note via a small delimited format, diffed against
  `memory/sources/notes_index.json` (keyed on note id, falling back to a name+creation-date hash) so a
  new note emits an episode (`origin: "apple-notes"`, folder name as a tag hint), an edited note
  (changed modification date) re-emits an updated episode, and an unchanged note is skipped; plaintext
  capped at 20k chars. The one real I/O seam (`_run_osascript`) is the sole thing tests monkeypatch —
  **no test ever invokes real `osascript`** (TCC-prompt-safe). Both wired into `api/routers/sources.py`
  mirroring the feeds/bookmark-sync endpoint shapes exactly: `GET/POST/DELETE /sources/calendars`,
  `POST /sources/poll-calendars`, `POST /sources/sync-notes`. 52 new hermetic tests (444 -> 496 green).
  → relates to **R6** (connectors as Awake-phase episode emitters — was explicitly deferred there),
  **G9** (origin provenance — both origins flow straight into `GET /origins`, no changes needed there).
- ✅ **2026-07-14 — end-to-end consolidation run on live data (agentic Sonnet-5 path, zero API keys):**
  full Sleep-cycle-shaped consolidation exercised against real captured data — **786 bookmarks + 193
  notes → 988 episodes → 442 claims, 74 new entities, 805 zero-claim episodes** — via the agentic
  (Claude-Code-driven) extraction path, no OpenRouter/OpenAI key required. Live testing against real
  data (not fixtures) surfaced two bugs, both root-caused and fixed same-day: **(1) origin-attribution
  gap** — bookmark-synced episodes and their media entities carried `source: bookmark` but never
  `origin:`, so the Capture page's origins strip bucketed all of them under "Unknown" (`RawItem.origin`
  now threads explicitly from `bookmark_sync._tag_origin` through `media_ingestor.write_media_episode`/
  `write_media_entity` into both frontmatters; `api/scripts/backfill_bookmark_origins.py` repairs
  already-ingested files); **(2) media filename byte-cap** — a GitHub bookmark whose OG title was a
  whole paragraph produced a `media-*.md` filename past the 255-byte filesystem limit (`OSError Errno
  63`), and because `url_index` only records successful ingests, the failing URL retried forever on
  every sync (`_media_entity_id` now caps the slug at ~120 UTF-8 bytes and appends an 8-hex-char
  content-hash suffix on truncation so two long titles can't collide). → relates to **G9** (origin
  provenance), **M4** (media ingestion), **G10** (agentic bulk-extraction path).

## APPLY — buildable now (low architecture risk)

| ID | Item | Notes | Status |
|----|------|-------|--------|
| A1 | **Per-commit diff view in node history** | Expand entity history to show added-vs-removed (git diff per entity per commit). Builds on existing `/entities/{id}/history`. | ✅ |
| A2 | **Contributors view** | Which LLM model wrote which contribution to memory. Record model id in Sleep commit metadata/trailers; surface a "contributors" view + per-node attribution. | ✅ |
| A3 | **Animated bookworm on ingestion page** | Reuse the menu-bar tamagotchi sprite/state machine on the conversation-upload/ingestion screen. | ✅ (M4 — `BookwormView` animates in `UploadOverlay`) |
| A4 | **Enrich `skill` entity capture** | Store "Rodrigo usually asks to do X a certain way" (e.g. FastAPI project layout & repo structure conventions). Procedural-preference skills. → ties to D2/D5. | 🔲 |
| A5 | **Explicit gap analysis ("I don't know")** | Retrieval/answer surface admits what it does NOT know (no edge between X/Y, low confidence, stale `last_referenced`). Endorsed by both Honcho & gbrain notes. → ties to D3. | ✅ (M2 — `ask_service` explicit `gaps` + honest no-LLM gap path) |

> Note: A4/A5 partly depend on the decisions below; listed here because the mechanics are
> low-risk even if the framing shifts.

## RESEARCH — findings documented by background workflow

✅ **Done (2026-06-16).** Findings + synthesis in [`../inspiration/research/`](../inspiration/research/)
([index & cross-cutting synthesis](../inspiration/research/README.md)).

| ID | Topic | Headline recommendation | Status |
|----|-------|-------------------------|--------|
| R1 | [Why Honcho is good (deep)](../inspiration/research/r1-honcho-philosophy.md) | Steal the Dialectic NL-ask front door; reject the opaque substrate. Cicada's ask can be git-blame auditable — thesis-novel. | ✅ |
| R2 | [SkillOpt (Microsoft)](../inspiration/research/r2-skillopt.md) | Adopt the *governance pattern* (failure ledger + bounded gated rewrites), not the optimizer. Ungoverned self-improving skills drift net-negative. | ✅ |
| R3 | [Postgres+pgvector vs markdown+git+LEANN](../inspiration/research/r3-postgres-pgvector.md) | Keep markdown+git as source of truth; **replace LEANN with a Sleep-rebuilt stored-embedding index** (sqlite-vec default, pgvector as upgrade path). | ✅ |
| R4 | [Contextual / multi-dimensional entities](../inspiration/research/r4-contextual-entities.md) | One canonical entity + optional named **facets** (per-context lenses, independent decay). Reject separate per-context graphs. | ✅ |
| R5 | [Cost model for reconsolidation](../inspiration/research/r5-reconsolidation-cost.md) | Cheap ($1–4 cheap-tier / $10–20 quality per full pass). Cost isn't the constraint. Nightly incremental cheap-tier; route only conflicts to Sonnet/Opus. | ✅ |
| R6 | [Sync connectors](../inspiration/research/r6-sync-connectors.md) | Build connectors as Awake-phase **episode emitters** (zero new Sleep code). Ship keyless bookmarks HTML + RSS first; defer Notes/Spotify/Readwise. | ✅ |
| R7 | [Entity promotion: keep or kill?](../inspiration/research/r7-entity-promotion.md) | **Soften, don't kill**: hard 2nd-mention gate → decay-pruned shadow/candidate entities. Unbundle "promotion gate" from "closed taxonomy". | ✅ |
| R8 | [Peer / observer-observed model](../inspiration/research/r8-peer-model.md) | Don't build the full peer network for single-user. Adopt the cheap slice (opinion-vs-observed split); design a peer-ready `observer`-defaults-to-`self` substrate. | ✅ |

## DESIGN — new structures (proposals, pending decisions)

| ID | Item | Notes | Status |
|----|------|-------|--------|
| G1 | **Multiple memory banks / "memory projects"** (→ **M6, committed, next-up**) | Several named memory banks so the live consolidated graph is never erased: a **project dropdown in the Memory/graph page** to switch the active bank; **save the current graph under a name**; **create a new (empty/seed) bank** to test against (e.g. a bank seeded from imported chat exports + the big-model M5d consolidation). Backend: a banks registry + `memory_path` resolves to the active bank (legacy `memory/` = the default bank); `GET/POST /banks`, activate, duplicate-as-name. Banks can cross-reference. → ties to D2/D4/G12. **Rodrigo confirmed: build this now, before reviewing the demo surfaces.** | ✅ (M6 — `bank_registry` + `/banks` routers + app `BankSwitcher`; cc58eb5, b0f192f) |
| G2 | **Extend entity taxonomy** | New types: website/bookmark, research paper, idea, project-note, recipe, song/media, … Reference e.g. a song on another entity's wiki page with a personal-relevance note. → gated by D2. | ❓ |
| G3 | **Bookworm "feed" knowledge page** | Sync-driven feed (bookmarks first), each item an entity with summary + *personal* relevance. Filterable view across articles/bookmarks/songs by a **relevance metric**. | ✅ (M4 — RSS connector + `GET /sources?sort=relevance` + `FeedView`; `personal_relevance` frontmatter added, read-only for now) |
| G4 | **Problem-log entity sections** | "We solved this problem by doing X" + open-ended "we discussed this — how did it end up going?" Likely sections under project/concept entities. | 🔲 |
| G5 | **"Project improvements" sections** | Things discussed to improve on a given project. Probably a section grammar under `project` entities. | 🔲 |
| G6 | **Entity-type audit interface** | A way to easily audit which entity types exist and structure info per type (section grammar per type). Meta-tooling over the taxonomy. | 🔲 |
| G7 | **Reduce Rodrigo-node centrality** | "Rodrigo" is over-central; introduce more intermediate hub/bridge nodes. Overlaps v2 hubs work. | 🔲 |
| G8 | **Agent-research memory + opinions** | Memory of agents' work (e.g. the Honcho mini-research, with raw traces). A second agent can add an *opinion* → two versions of the same memory side by side (observer/observed). → ties to D4/R8. | ❓ |
| G10 💸 | **Bulk re-extraction under the new architecture (big model)** | Re-run entity/claim extraction over the **full Claude.ai + ChatGPT conversation export corpus** (as Rodrigo did once before) but with the **new D2 claim-layer architecture** in mind, using a **big/high-quality model** (planned: buy OpenRouter or similar credits). Quality goals: (1) **richer, more detailed per-page summaries** (the current pages are critically thin — median ≈50 words); (2) **avoid nonsense single-mention entities** (graph pollution — handled by the new `activation`/candidate gate, not a hard count); (3) surface **better intermediate/abstraction concepts** that encapsulate many things (intermediate "in-between" nodes — relates to G7 Rodrigo-centrality + hubs + abstract cross-links). This **IS the D2 migration's full-backfill / re-consolidation step** — but done deliberately for *quality*, not the cheap lazy path. **Design fork to decide: extraction engine.** (a) **Python Sleep cycle** (current) — deterministic, has the 5 structured stages (resolution/conflict/decay/index), but extraction is a single structured litellm call per episode. (b) **Claude-Code-driven agentic extraction** (Rodrigo's idea) — a Claude Code *workflow/skill* reads an episode batch and writes to the graph via the MCP Bookworm tools, giving a big reasoning model full agentic latitude to write rich pages + choose intermediate concepts (and dogfoods the agent-facing write path; pairs with G9 `origin: claude-code`). Tension: (b) is richer but less deterministic/idempotent and may skip the structured resolution/decay logic. **Likely best = hybrid:** agent does the rich extraction/summarization + concept abstraction; the deterministic pipeline still owns dedup, contradiction (bi-temporal close), decay, and indexing — i.e. the agent writes *claims* through MCP tools that enforce the structure. → gated by D2 final architecture; feeds the M5 migration build plan. | 🔲 |
| G9 | **Cross-harness episode sync + origin provenance** | Two linked parts. **(a) Sync queue:** a standardized way for *any* agent harness — Claude Code, Codex, Cursor, OpenCLAW, ChatGPT/Claude exports, future personal-agent harnesses — to push its conversation episodes into a queue that feeds Cicada's `episodes/` inbox. Each harness is a thin "episode emitter" (same principle as the M4 media/RSS connectors); options to investigate: MCP `cicada_save_episode` (already exists, MCP-native), harness hooks/stop-hooks that dump transcripts, a file-drop/watch queue, or a small ingest API. Must be source-agnostic and dedup-safe (content hash). **(b) Origin provenance:** record the **origin harness** of each episode/memory as a first-class provenance dimension — *distinct from the M3 contributor*. M3's `Cicada-Author` trailer answers "which **model** wrote this memory"; G9 answers "which **harness/client** the memory **originated from**" (e.g. `origin: claude-code`). Propagate `origin` from episode frontmatter → entities/claims (via `source_episodes`) → a contributors-style view filterable by harness. The episode `source` field is a partial foundation; this makes origin a tracked, end-to-end, queryable dimension. → relates to M3 (contributors), R6 (connectors-as-emitters), D2 (claim/observer model: `origin` pairs naturally with the `observer`/`source_trust` fields in the new architecture). | ✅ (2026-07-03 — origin stamped on episodes/media across all connectors; `GET /origins` provenance aggregation. App origins strip shipped `03ebe5e` — G9 fully done end-to-end.) Sync-queue half via episodes/ + connectors. |
| G11 | **In-app media preview (images · videos · websites) + artifacts as memories** | Preview rich media **inside the app**: **images** (inline + lightbox), **videos** (inline player / thumbnail-to-play), and **website link previews** (Open-Graph card or a small embedded web view of saved bookmarks/URLs — reuse the M4 media-ingestion OG enrichment for the card; a `WKWebView` for full preview). Let media-as-artifacts be **saved as memories** — an image/video/site embedded in an entity or claim, rendered inline like the transclusion layer renders embedded pages. Extends the inline-transclusion model (`![[…]]`) to media embeds (D2 transclusion currently excludes images/media — revisit) and the M4 `media` entities (which already store `url`/`thumbnail`/`media_type`) gain real in-app previews instead of just opening the URL. Sources: chat-export images (Gemini takeout), saved bookmarks/YouTube/articles, pasted/diagram artifacts. → **underpins G14** (mood-boards are media-preview-heavy); relates to G2 (media types), G3/M4 (feed), the transclusion layer, M5c surfaces. | 🔲 |
| G12 | **Chat-history import queue (export → bank, date-preserving)** (→ **M7, committed, next-up**) | A UI + pipeline to **import past chat exports** (Claude `conversations.json`, ChatGPT export, Gemini `MyActivity.html`) — from the bookworm/ingestion panel **or a settings page** — and **consolidate them into a chosen bank: new or existing** (ties to G1/M6). **Must preserve original conversation dates** extracted from export metadata (Claude per-message/per-conversation `created_at`; Gemini activity timestamps) so the consolidated timeline is historically accurate — open question whether dates are reflected via backdated episode frontmatter / git-history (rebased) / a purely additive layer; **decision: backdate episode frontmatter to the real `created_at` (the Sleep pipeline + claim `valid_from` already key on dates), additive — don't rewrite git history.** Same export path Rodrigo uses manually today; this productizes it. Data staged outside the repo at `…/thesis/cicada-data/chat-exports/` (claude = `conversations.json` 29MB w/ dates ✓; gemini = `MyActivity.html` + images; openai = TBD). → feeds M5d (the big-model consolidation runs on these imported episodes into the new bank). → relates to G9 (origin: claude-export/chatgpt-export/gemini-export), G10/M5d. | ✅ (M7 — `/banks/{name}/import` + claude/chatgpt/gemini parsers + UploadOverlay import mode; dates backdated onto episode frontmatter; delta dedup = G20 d139c11) |
| G13 | **Application-wide tasks/ideas backlog (personal-assistant memory)** | Make the per-project backlog of **tasks / ideas / open-questions** a first-class **in-memory** artifact — the kind currently hand-annotated in this very file — captured from conversation, scoped per project/bank, surfaced proactively, and resolvable. Model as **claims** (`predicate: todo \| idea \| open-question \| improvement`, plus a `status: open \| in-progress \| done \| parked`) or a light task-entity, tied to the related project/concept entity. **Interactions to consolidate it:** (1) quick-capture — menu-bar bookworm "jot" / MCP `cicada_note` / Sleep extraction of actionables ("we should…", "idea:", "TODO"); (2) a per-project **"Tasks & Ideas" list/board view** (open · in-progress · done); (3) proactive surfacing via the **inbox** when a chat touches a related topic ("you had an open idea about X — still relevant?"); (4) a resolution loop where marking *done* writes a G4 problem-log "solved by X" claim, and *park* decays. **Dogfood demo:** this thesis's own backlog (`memory-evolution.md`) becomes a Cicada project/bank. → generalizes G4/G5; uses the inbox + claim/status model + bank scoping (M6). | 🔲 |
| G14 | **Aesthetics / mood-board entities (postponed — captured)** | A first-class **`aesthetic`/mood-board** entity — image-heavy, video/Pinterest links, artifact-like — for storing designs, references, and aesthetics that **recur across projects/ideas**. Rich interlinking: an aesthetic relates to other aesthetics and *influences* projects (Rodrigo's example: **Blade Runner → futuristic cyberpunk → a robot-design project**). A **dedicated gallery/board view** (not the force graph): image grid + embedded links + descriptions, cross-referenced, where Rodrigo captures self-made designs and links them to Pinterest boards / external refs and reuses aesthetics across projects. Like a visual/creative cousin of `skill`. **Depends on G11** (in-app image rendering) + extends **G2** (media taxonomy) + the **transclusion** layer (embed boards/images as `![[…]]`). Postponed per Rodrigo. → relates to G2, G11, transclusion, the claim relationship model. | 🔲 |
| G15 | **Contributor avatars/icons on the Contributors page** | Give each contributor a visual identity (GitHub-repo-contributors style). **Human/`user`** writes (manual edits, clarifications) → the user's **GitHub profile picture**. **LLM** contributors → the **provider's company icon** (Anthropic / OpenAI / Google DeepMind — keep it to the company logo for now, not per-model). **`unknown`** (legacy untrailered commits) → a generic unknown-contributor icon. Small UX polish on M3's `/contributors` view; needs a provider→icon map + the user's GitHub handle (config) for the avatar. → relates to M3 (contributors), G9 (origin). | ✅ |
| G16 | **Shared memories + shared contributors (open exploration)** | Down-the-line: the ability to **share memories** between people and have **shared contributors** on a memory/bank — collaborative memory (a bank with multiple human + agent contributors, à la a shared repo). Pairs naturally with the peer/observer model (R8) and the contributors/origin provenance. **Left open for exploration later** per Rodrigo — not scoped yet. → relates to R8 (peers), M3 (contributors), G1 (banks), D4. | 🔲 |
| G17 | **Deadlines/dates as claims, not entities** | Deprecate the standalone `deadline` entity type; model deadlines/dates as **dated claims/fields on the thing they belong to** — `(subject: capstone, predicate: due, object: 2026-07-01)` or a `due:` frontmatter field — surfaced at the top of that entity's page. **Rationale (Rodrigo + observed):** standalone date nodes are thin and pollute the graph — the inbox literally flagged "**July 8th**" as a possible-duplicate entity, exactly this. Dated claims are also queryable ("what's due this week"). Maybe research-confirm first, but the lean is **drop `deadline` as a type**. → D2 taxonomy; uses the CPCG claim model (predicate `due`). | ✅ core (0f2c46c — extractor forbids `deadline` entities, emits `due` relationships/claims; enum removal deferred to G19) |
| G18 | **Split `location` → `directory` vs physical place** | `location` is the wrong word for filesystem directories (Rodrigo). Split into **`directory`** (folder/path — a filesystem dir; **this** is what the location path+contents browsing should target) vs **`location`** (a physical real-world place — home city, conference, office). The Sleep extractor classifies by shape (a `/Users/…` path → `directory`; a place name → `location`); the directory-listing endpoint keys off `directory`. → D2 taxonomy; ties to the location path+contents feature. | ✅ (0f2c46c + cc58eb5 — `directory` entity type + shape-based classification + dir-listing endpoint) |
| G19 | **Deprecation & dead-code sweep (keep repo + app clean)** | Per Rodrigo: periodically deprecate/remove old code no longer used so the repo + application stay clean. **Current candidates:** (a) the legacy entity-path `conflict_resolver` now running *alongside* the M5f claim pipeline (additive — retire the legacy entity consolidation once claims fully take over); (b) the legacy `pending_entities.jsonl` store; (c) stale `leann`/`rebuild_leann` naming + the `_leann_*` function names (LEANN removed in M1/M3); (d) the `deadline`/`location` taxonomy (→ G17/G18); (e) the new **provider factory is built but dormant** — production services still call litellm inline, so either *adopt* the factory or remove it (M5-prep); (f) stray `.claude/settings.json.bak`; (g) mark superseded specs (`d2-recommendation.md` → superseded by `d2-architecture-final.md`); (h) prune any unused Swift views/components after the UI churn. → ongoing hygiene; revisit each milestone. | 🔲 |
| G20 | **Incremental / delta re-import (ongoing-memory loop)** (→ build BEFORE the first big import) | Re-uploading a fresh conversation export consolidates **only new + changed threads**, not the whole corpus. Key the import dedup on the source conversation **`uuid` + `updated_at`** (both in the Claude/ChatGPT exports), stamped onto each episode's frontmatter at import. On re-upload: brand-new conversation (uuid unseen) → new episode; unchanged (same uuid+updated_at) → skip; **grown (same uuid, newer updated_at / more messages) → update that episode + re-queue it (`processed: false`)**. Sleep then consolidates only the unprocessed (new+changed) episodes; the CPCG claim pipeline's bi-temporal trust-reconciliation merges the re-consolidated content cleanly (no dupes, supersedes changed beliefs, preserves human edits). **Must ship BEFORE the first big import** so episodes carry the uuid from the start, so every future re-export "just works." → the feature that makes "periodically feed your conversations → updated graph" real (the distribution story); relates to M7 import, M5f claim pipeline, G9 origin. **Shipped `d139c11`** — parsers carry uuid+updated_at; `_stage_episodes` returns (created, updated, skipped); grown threads rewrite in place + requeue (`processed:false`); `episodesUpdated` surfaced in upload/import UI; 8 new tests. | ✅ |
| G21 | **Full-graph dedup sweep (Sleep self-healing)** | The Stage-2 resolver already does confidence-based LLM dedup, but **incrementally** — it only compares NEWLY-extracted entities against the existing graph. Two entities that both already exist and aren't re-mentioned (e.g. `Diego` from run 1 vs `Diego Sanmartín` from run 3) never get re-compared, so residual dups accumulate. Add a periodic full-graph pass: embedding-gate existing-entity pairs (same type, high cosine) → LLM same/different/unsure judge with BOTH pages' context → auto-merge high-confidence (combine pages/claims/relationships, repoint edges + wikilinks, delete loser), nudge the uncertain. Runs every Sleep (or every N) so the graph self-heals instead of needing manual merges. Embedding-gating keeps it cheap (only judge plausible pairs). → user-proposed 2026-06-18; the proper fix for "duplicates I have to merge by hand". Needs a real entity-merge primitive (the current inbox merge path absorbs a *mention*, it doesn't consolidate two rich entities). | 🛠️ done-pending-merge (`api/services/dedup_sweep.py` core logic + tests landed; `POST /maintenance/dedup-sweep` production endpoint being wired today, in a parallel branch). |

## Media, previews & capture channels (Rodrigo — 2026-07-03)

New backlog captured from two notes on 2026-07-03. Theme: make memory **media-rich and multi-channel** — videos/images as first-class memories with agent-generated summaries grounded in transcripts, an image-rich preview layer in the app (less "Obsidian vault", more interactive), and low-friction capture from the places Rodrigo already saves things (messaging apps, browser bookmarks). Several extend existing items (G2 taxonomy, G3/M4 feed, G9 origin, G11 media preview, G14 mood-boards, R6 connectors) — cross-referenced, not duplicated.

| ID | Item | Notes | Status |
|----|------|-------|--------|
| G22 | **Video & frame/image entities + "watch video" agent skill** | First-class **`video`** entities (a link/reference to the video) and **`image`/`frame`** entities. **Source of truth = the video's transcript/captions**, stored with the entity; the *agent* watches the video (via a Claude video skill — Rodrigo flagged [`bradautomates/claude-video`](https://github.com/bradautomates/claude-video), not yet set up) and saves a **summary + any discussion thoughts** relevant to the conversation as the entity body. Later a query like *"show me all the robotics videos I've saved for my research"* surfaces them and the agent knows what each entails. → extends **G2** (media taxonomy), builds on `cicada_save_url`; the summary-grounded-in-transcript pattern is the media cousin of **Phase 3 source-grounded rewrite** (`docs/superpowers/specs/2026-07-03-retrieval-and-bookworm-improvement-design.md`). | 🛠️ partial (save path `cicada_save_url` + the `/watch`→save chain via the `cicada-librarian` skill; a first-class `video` entity schema + rich in-app rendering = the G23/G25 wave, buildable now) |
| G23 | **In-app rich media preview (YouTube playback + thumbnails + hover previews)** | In the companion app, opening a video link (or a video markdown) renders the **thumbnail/preview**, and — nice-to-have — **plays the YouTube video inside the app** (WKWebView). **Hovering** a video-link reference shows its thumbnail. → extends **G11** (already ships image lightbox, inline video, website WKWebView); adds in-app YT playback + hover previews. | ✅ (2026-07-03 — HeroPreview atop entity pages: YouTube in-app embed player, OG/website hero card, hero image w/ lightbox; reuses MediaPreview/WebView) |
| G24 | **Summary box at the top of markdown previews** | When a markdown is opened in the app, render a **summary box at the very top** of the preview — for a video/link entity, "what this video/article is about"; **generally, a short human-readable summary at the top of every entity preview** so the user can read the gist fast. → app-side render of the `## Summary` section; pairs with G22/G25. | ✅ (SummaryBox atop EntityDetailCard rendered tab; extracts ## Summary) |
| G25 | **General entity "hero" preview system (image-rich)** | A general mechanism for a **hero preview at the top of an entity page**: a **location** shows a saved image of the place; a **book/article/blog** shows a rendered **website/Open-Graph preview**; a **video** shows its thumbnail/player. Same behavior on **hover** over a reference. Goal (Rodrigo): move the app away from a plain Obsidian-vault list toward an **interactive, image-forward** feel. → depends on **G11/G23**, extends media entities and **G14** (mood-boards). | ✅ (2026-07-03 — hero preview system on entity pages, image-rich; hover-preview on graph refs = follow-up) |
| G26 | **Light mode / dark mode toggle** | Add a **light theme** to the companion app (today `CicadaTheme` is dark-only) with a user toggle + persisted preference. → needs a light palette parallel to the current tokens + a theme preference; the graph.js/d3 colors and `CicadaTheme` must both switch. | ✅ (light/dark toggle in sidebar footer; CicadaTheme mode + light palette; graph.js webview themed = TODO) |
| G27 | **Local file/folder references in markdown (device-aware paths)** | Let a markdown reference a **file or folder path on the computer** (e.g. a directory of images, or a specific image of a location) via the path. Add a **`device`/`device_location`** parameter so that when memory is imported to **another computer**, a path known to not exist there degrades gracefully rather than being a dead link. The app must (a) **detect when referenced files move** and refresh the stored path, and (b) **handle a now-missing file** without a dead-end reference (surface "file moved/removed", offer to relink). → relates to **G18** (directory entity type) and the media/preview layer. | ✅ (2026-07-03 — `local_refs` service + `GET /local-ref`: present/moved/other-device, existence-only; app relink path) |
| G28 | **Bookworm "sleeping" animation (zzz) + sprite screenshots** | Give the menu-bar bookworm mascot a **sleeping animation**: a **"zzz"** rising when the worm is asleep (Sleep cycle running / idle-asleep). **Task Rodrigo named: spawn a subagent to capture screenshots of the current worm avatar sprites** and design/implement the zzz animation frames. → extends `BookwormSprites`/`BookwormState`/`MenuBarManager` (the sprite state machine already has awake/sleeping/digesting/etc.). | ✅ (zzz frames wired into frames(for:.sleeping) + BookwormView animation; live when a Sleep cycle runs) |
| G29 | **Messaging-app capture channel (Telegram / WhatsApp → memory)** | Link a **messaging app (Telegram or WhatsApp)** as a personal capture channel: Rodrigo forwards **himself** links / videos / notes ("watch later", to-dos, interesting posts) and they consolidate into memory, referenceable later. **Two parts:** (1) **content extraction** — the *importance* + *what the link/video contains* (via the G22 watch-video skill / OG scrape), so a saved LinkedIn post of "a robot tying a knot from one human demo video" is summarized and later surfaces under "robotics videos for my research"; (2) the **messaging connector as an Awake-phase episode/media emitter** (same principle as R6 connectors). → the Telegram bot (`/save` `/note` `/remind`) is already in the CLAUDE.md vision; this makes it real. Relates to **R6, G9** (origin: telegram/whatsapp), **G22, G13** (to-do/idea backlog). | ✅ backend + onboarding (2026-07-03 — `telegram_capture` + `POST /capture/telegram` token-gated; synced-apps setup page with @BotFather→token→webhook steps. **Activate:** user sets `CICADA_TELEGRAM_BOT_TOKEN` + webhook) |
| G30 | **Browser bookmark ingestion (Chrome + Safari, incl. iPhone)** | Import **Chrome and Safari bookmarks** (including **Safari on iPhone**) as saved-for-later media entities — same "save for later → consolidate → retrievable" pattern as G29. → **M4** already ships a Netscape-bookmarks HTML + Chrome JSON importer; this adds **Safari** (+ mobile) and a periodic sync loop. Relates to **G3/M4** (feed), **R6, G29**. | ✅ (2026-07-03 — Safari `.plist`/HTML import (G30) + keyless Chrome/Safari `sync_bookmarks` local-file diff → `POST /sources/sync-bookmarks`; Capture page "Sync now") |

## Context passport domains — app-sync & share-target (2026-07-13)

New backlog from the [`context-passport-roadmap.md`](context-passport-roadmap.md) gap analysis (code-verified two-agent audit against `dev` @ `ca345c9`) plus explicit owner requests. Cicada is a **passport of oneself** — conversations/bookmarks/projects/people/skills/calendar are covered; music, maps/travel, possessions/wishlist, and fitness are absent (❌ in the roadmap's coverage map). All connectors follow the shipped pattern: **keyless/local-first, episodes at capture, no LLM, dedup index, origin tag, Sleep consolidates** (`bookmark_sync.py`, `feed_registry.py`, `calendar_registry.py`, `notes_sync.py` are the four shipped templates).

| ID | Item | Notes | Status |
|----|------|-------|--------|
| G31 | **Music sync — Apple Music connector** | AppleScript batch enumeration of Music.app (play counts, played date, loved, persistent ID) — near-copy of `notes_sync.py`, same TCC consent model. `music_index.json` dedup, `origin: apple-music`. → **Track B1** of `context-passport-roadmap.md`. | 🔲 |
| G32 | **Music sync — Spotify extended-streaming-history import** | Extended Streaming History export zip → import queue (keyless; export can take up to ~30 days to arrive — ship G31 first). Aggregation policy (per-track vs per-session episodes) is the main design decision. → **Track B1b**. | 🔲 |
| G33 | **Maps sync — Google Maps saved/visited places + Apple Maps guides** | Google Takeout import of Saved Places + Semantic Location History (schema-drift risk, keep parser defensive); Apple Maps guides if/when Apple ships an export path. Feeds the G35 `visited`/`wants-to-visit` claims onto `location` entities. → **Track B3**. | 🔲 |
| G34 | **Possessions / wishlist / likes as claims** | Not a new entity type — first-person claims via new Telegram verbs `/own`, `/want`, `/like` + the existing `cicada_write_claim` path (trust-gated, ambiguity-guarded) + the A3 predicate seeds (`owns`/`wants`/`likes`). → **Track B2**. | 🔲 |
| G35 | **Travel semantics — visited / wants-to-visit claims** | `visited` / `wants-to-visit` predicates (A3) on `location` entities, populated from conversation + the G33 Maps import. Split out from G33 because it's the semantic/claim layer the import feeds, not the import itself. → **Track B3**. | 🔲 |
| G36 | **Fitness — Apple Health `export.zip` importer** | `export.zip` → import queue, `iterparse` (files reach GBs), daily-rollup episodes (not per-sample). Inherently manual sync loop (iPhone export + AirDrop) — no macOS API exists. Do last or on explicit demand. → **Track B4**; extended later by G45 (clinical records). | 🔲 |
| G37 | **Share Target — Cicada in the macOS share sheet** | Ship the **Share Extension** already flagged "Coming soon" in `SyncSetupView` so any Mac app with a share button can export straight to Cicada (same capture principle as G29/G30 — one more emitter). An **iOS companion app** is the natural later extension of the same idea (share sheet on iPhone); not scoped now, revisit once D2 (.dmg) ships. → **Track D3**. | 🔲 |
| G38 | **"Sync other apps" — connector pattern umbrella** | Not new work — a pointer for future sessions: every domain connector above (G31–G36, G39–G46 below) follows the same **keyless/local-first, episodes at capture, no LLM, dedup index, origin tag, Sleep consolidates** template already proven by `bookmark_sync.py`/`feed_registry.py`/`calendar_registry.py`/`notes_sync.py`. A new "sync app X" request should default to this pattern before inventing a new one. | 🔲 |

## Absent passport domains — human-experience research (2026-07-13)

20 additional life domains surveyed beyond what Cicada already scopes, from a feasibility research pass. Opinionated take carried over: the highest-value additions are domains that are (a) already sitting in a local SQLite/XML file with zero API key and zero cloud round-trip, and (b) reflect *deliberate* signal (something the user chose to save/highlight/finish) rather than ambient exhaust (browsing history, screen time, raw transactions). Apple Books highlights and Photos metadata (via `osxphotos`) are the best-ROI connectors found — trivial to build, dense/durable context, fully keyless. Two domains from the research are **not** new line items: **Sleep-tracking** data is already covered by G36 (Apple Health), and most of **family milestones** is already covered by G46 (Contacts birthdays) + the existing calendar backlog (Track B5) — the only novel piece (a non-calendared one-off like "niece born") stays on the manual `/note` verb, no dedicated connector.

| ID | Item | Notes | Status |
|----|------|-------|--------|
| G39 | **Reading — Apple Books highlights & notes** | Direct read-only SQLite query against `~/Library/Containers/com.apple.iBooksX/Data/Documents/AEAnnotation/AEAnnotation_v10312011_1727_local.sqlite` — no export step, just Full Disk Access. One episode per highlight/note, keyed to book + timestamp. Highest-ROI connector found in the research pass. | 🔲 |
| G40 | **Reading — Kindle highlights** | USB-connect Kindle, copy `documents/My Clippings.txt` (plain text) into a watch-folder; one episode per clipping. No cloud/API route exists for full history (Send-to-Kindle sync is inconsistent). | 🔲 |
| G41 | **Photo metadata (people · places · dates — not pixels)** | `osxphotos` CLI (MIT, local, actively maintained) run via launchd, exporting JSON metadata only (keywords, persons, reverse-geocoded location, album, date) — explicitly skip pixel export. Zero network calls, zero API key. Second-best-ROI connector found. | 🔲 |
| G42 | **Journaling / mood / dreams** | New Telegram verbs `/journal`, `/dream` (same staging pattern as `/save`/`/note`); optional Day One local JSON export for backfill. Richer first-person internal-state signal than sentiment inferred from chat logs. | 🔲 |
| G43 | **Voice memos** | Local Whisper transcription (same approach already used for Telegram voice notes) over `.m4a` files under `~/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings` → one episode per memo. Zero cloud. | 🔲 |
| G44 | **Education, courses & certificates** | LinkedIn data export (`Certifications.csv`/`Education.csv`) + Coursera/edX/Udemy certificate PDFs dropped into a watch-folder. No unified keyless API across providers — stays multi-source and periodic. Durable, dated, resume-shaped facts anchoring `skill`/`concept` entities. | 🔲 |
| G45 | **Health Records (clinical, beyond fitness)** | Extend the **G36** Apple Health connector's field mapping — `export.zip` already includes FHIR-sourced Clinical Record resource types (allergies, medications, conditions, immunizations) alongside fitness data once the user links a provider in Health.app. Recommend explicit opt-in given sensitivity, even though the route itself is keyless and local. | 🔲 |
| G46 | **Contacts (macOS Contacts.app)** | Read-only AppleScript/EventKit enumeration of Contacts.app (birthdays, employer, related-names), local, no network call, gated by the standard macOS Automation permission prompt. Feeds entity resolution as corroborating metadata (not raw episodes) — cuts clarification-queue load for recurring names; also covers most of family-milestone birthdays (see subsection intro). | 🔲 |
| G47 | **Saved-content importer family (Instagram saved + YouTube playlists, …)** | Neither Instagram nor YouTube exposes "saved" items via a usable public API (Meta is export-only; YouTube's Watch Later playlist API has been dead since 2016), so this family rides the existing keyless **export-file** import path (`media_ingestor.parse_upload`), same as bookmarks/RSS/Takeout. **Shipped this change:** (1) **Instagram saved** — parses the Meta "Download your information" `saved_saved_media` JSON (incl. a collections variant grouping saves under collection names → `folder`), `origin: instagram-saved`; (2) **YouTube playlists** — parses a per-playlist Takeout CSV (playlist name from filename → `folder`, no titles — oEmbed enrichment fills them at ingest), `origin: youtube-playlist`, plus a whole-Takeout-zip walk (`playlists/*.csv` + `watch-history.json` in one drop). **Future members of the same family** (each has an official data-export file, same keyless/local-first pattern — no new architecture, just a new parser + sniff rule): **TikTok favorites** (`favorite_videos.txt` in the TikTok "Download your data" export), **Reddit saved** (`saved_posts.csv` in the Reddit data export), **X/Twitter bookmarks** (no bulk-export today — would need X's data-export `bookmarks.js`, revisit if/when that ships). → extends **G30** (bookmark ingestion) and **G9** (origin provenance); cross-refs roadmap **Track B** (`context-passport-roadmap.md`) as a new saved-content sub-item alongside B1–B8. | ✅ (this change — Instagram saved + YouTube playlist/zip importers; TikTok/Reddit/X listed as future members) |

**Explored, deliberately deferred** (medium/low priority — kept here so future sessions know they were considered, not missed):

- **Podcasts listened** (medium) — Apple Podcasts local SQLite (`MTLibrary.sqlite`) is queryable, but lower-intentionality interest signal than reading/highlights; not worth a dedicated connector yet.
- **Movies/TV/games watched or played** (medium) — Letterboxd/Trakt CSV export covers movies/TV; games have no cross-platform export (Steam/PlayStation/Xbox all differ) — falls to the manual `/note` verb, not a connector.
- **Food, recipes, restaurants** (medium) — no structured export exists (Apple Maps guides don't export cleanly); reuse the G37 share-sheet save pattern for links, `/note` for offline meals — manual-first.
- **Subscriptions & recurring financial commitments** (medium) — Settings > Subscriptions has no Shortcuts/AppleScript export path; realistic route is manual entry or an on-device OCR pass that extracts only renewal dates and discards the screenshot.
- **Pets** (medium) — no export path exists by definition; pure manual capture via `/note` or a companion-app quick-add.
- **YouTube watch history** (medium) — Google Takeout JSON exists but requires a manual multi-step web flow each time (no automatable keyless route); diluted by autoplay/impulse clicks vs. deliberate saves.
- **Email (Mail.app)** (low) — rich in commitments/relationships, but full-inbox import is a privacy and noise disaster; only viable metadata-scoped-by-default with opt-in full-body capture — the noise-filtering/scoping logic is most of the work.
- **Browsing history & screen time / app usage** (low) — ambient exhaust, not deliberate signal (the opposite of bookmarks/RSS); ingesting reads as self-surveillance. If ever built: weekly aggregate stats only, never per-URL/per-app episodes.
- **Finances — transactions & purchase history** (low) — high-noise, high-sensitivity, mostly redundant with possessions/subscriptions already scoped (G34); poor context-per-privacy-risk ratio. If ever built: monthly category totals only, source CSV never persisted.
- **Documents & identity records** (low) — the metadata (an expiry date) is useful; the document content (a scanned passport number) is a liability with ~zero marginal context. If ever built: on-device Vision OCR extracts only a date, discards the scan.
- **Giving/volunteering & home/vehicle logistics** (low) — real but sparse/low-frequency; no universal export exists across charities/DMV/dealerships — catch-all via `/note`, not a connector.

---

## Repo-link layer (2026-07-13)

Project/directory entities can now declare a `repos:` frontmatter key linking them to local
git checkouts (path, optional device/remote/default_branch, optional declared `worktrees:`
list). `GET/PATCH /entities/{id}/repos` reads/writes only that key; live git context (current
branch, ahead/behind, dirty files, per-worktree state) is resolved **on demand and never
cached** — `git_service` shells out fresh on every call rather than persisting observed state
to disk. Surfaced in the graph as synthetic `repo:<slug>` nodes (one per distinct declared
path, edge "has repo" from the owning entity), and via the `cicada_repo_context` MCP tool.
See root `CLAUDE.md`'s "Repo links" subsection for the full frontmatter shape.

---

## Live-conversation provenance & resume (2026-08-20)

Captured from Rodrigo 2026-08-20: memory should know not just *which harness* and *which model* wrote it, but *which specific live conversation* — and let you jump back into that conversation.

| ID | Item | Notes | Status |
|----|------|-------|--------|
| G48 | **Live-conversation provenance + "Recent conversations" resume list** | Track which **live conversations** (Claude Code sessions, Cursor chats, any MCP-connected harness) wrote to which part of memory, and surface them as a **"Recent conversations"** list you can **hop back into** (resume). Two parts. **(a) Conversation-level provenance:** today provenance answers *which model* (M3 `Cicada-Author`) and *which harness* (G9 `origin`) but not *which conversation*. Stamp a **`session_id`/conversation id** (+ optional transcript path / resume handle) onto episodes captured live via MCP (`cicada_save_episode`, `cicada_write_claim`), and propagate it episode → entities/claims via `source_episodes` — the exact pattern G9 used to thread `origin`. Claude Code exposes its session id to hooks/MCP context; other harnesses analogously; degrade gracefully when a harness offers none. **(b) Recent-conversations surface:** a recency-sorted list (app view + API endpoint) grouping memory writes by conversation — harness, model, timestamp, and *which entities/claims that conversation touched* — with a one-click **"Resume"** action that reopens the session (`claude --resume <session-id>` for Claude Code; per-harness deep-link where one exists, provenance-only fallback where not). Inverse navigation too: from an entity's history, jump to the conversation that wrote that belief, then back into it live. → extends **G9** (origin: harness → *conversation*), **M3/A2** (contributors: model → *session*); relates to **G12/M7** (imported conversations already carry per-conversation `uuid`s — same grouping applies, minus resume) and the entity history/provenance views. | 🔲 |

---

## Subscription-first portability (2026-08-21)

Captured from Rodrigo 2026-08-21: Cicada should be fully useful with **no API keys** — powered by the Claude or ChatGPT plan the user already pays for, connected into those same sessions. A 15-agent research workflow (repo grounding → Claude-plan/ChatGPT-plan/local-fallback/prior-art research → 5 adversarially verified claims → 3 candidate architectures → judged synthesis) produced [`subscription-first-portability.md`](subscription-first-portability.md).

| ID | Item | Notes | Status |
|----|------|-------|--------|
| G49 | **Subscription-only Cicada — the "Session-Native Engine Ladder"** | Adopt the recommended architecture in [`subscription-first-portability.md`](subscription-first-portability.md): a **Claude Code plugin** (SessionStart primer, Stop/SessionEnd auto-capture, PreCompact flush, both skills, MCP registration, new `cicada_commit` tool) with a **Codex CLI mirror** for ChatGPT-plan users; underneath, an **engine ladder** (implement the reserved `llm_mode="agent"`: subscription CLI `claude -p`/`codex exec` → local Ollama → BYOK → skip-with-queue) behind a mandatory `providers.resolve_llm_fn` seam; on top, **keyless onboarding** (plan-picker wizard replacing "paste your key" with vendor OAuth, ungated embedding default removing the HF_TOKEN gate, launchd nightly runner with env-key sanitization + stop-on-throttle). Two non-negotiables all three candidate designs converged on: a deterministic **"structural Sleep"** (decay/hubs/edges/index/inbox/git-commit — zero LLM, runs nightly no matter what, sweep-commits agentic writes) and **bearer-token auth on localhost:8000 as a launch blocker**. Phased P0–P5 (~5–7 solo weeks; Claude-plan user fully served after ~2). Key verified facts: `claude -p` runs on Pro/Max subscription OAuth (billing-split paused Jun 2026); published token-limit figures are **refuted** → budget in invocations + live throttle detection, never tokens. Re-confirm the doc's "NOT verified" checklist (hooks payloads, plugin marketplace, all Codex-side claims) before building each phase. → subsumes the engine half of **G10** (agentic extraction), extends **G9** (origin) + M3 (contributors, per-rung `Cicada-Author`), relates to G13, launch-blocker list, and `install.sh`/onboarding. | 🔲 |

---

## Connections, consumption dashboard & in-app ask (2026-08-28)

Captured from Rodrigo 2026-08-28. Design spec: [`../superpowers/specs/2026-08-28-connections-and-consumption-dashboard-design.md`](../superpowers/specs/2026-08-28-connections-and-consumption-dashboard-design.md); plans: [`provider-connections`](../superpowers/plans/2026-08-28-provider-connections.md) · [`consumption-dashboard`](../superpowers/plans/2026-08-28-consumption-dashboard.md). Research grounding (harness connection/usage UX, 2026-08-28): Claude Code `claude auth status --json` exposes `subscriptionType`; Anthropic forbids third-party apps intermediating claude.ai credentials (enforced since Feb 2026) → delegate to the CLI, never read the Keychain, never poll `/api/oauth/usage`; Codex `codex login status` + display-only JWT decode of `~/.codex/auth.json` (`chatgpt_plan_type`) + `codex login --device-auth` for a headless code flow; Claude Code's `~/.claude/stats-cache.json` is the cheap pre-aggregated source behind its `/stats`; LiteLLM's price table is the standard for usage-based cost.

| ID | Item | Notes | Status |
|----|------|-------|--------|
| G50 | **Provider connections — "sign in with your plan" for Claude, ChatGPT (OpenAI OAuth via Codex), others; BYOK; Ollama** | A `ConnectionAdapter` protocol (one file per provider under `api/services/connections/`): **Claude plan** = `claude auth status/login/logout` delegation (Max 5x/20x tier is a user pref, not read from the Keychain); **ChatGPT plan** = `codex login status` / `codex login --device-auth` (code + URL shown in-app) / `codex logout`, plan+email decoded display-only from the id_token; **BYOK** per provider (openai/anthropic/openrouter/gemini) with keys in `~/.cicada/secrets.env` (0600) hot-loaded into `os.environ`; **Ollama** probe. Registry + prefs (`~/.cicada/connections.json`, choices only — no tokens/emails/plan snapshots on disk), 30 s status cache. `GET/POST /connections…` endpoints; `/status` gains `connections.{connected, engine}`. App: **Connections** page (Setup) with plan badge + price line (from `pricing.SUBSCRIPTION_PRICES`, verified 2026-08-28), Connect (Terminal hand-off for Claude, device-code sheet for Codex, SecureField for keys), Disconnect. **Prereq built in as Task 1: bearer-token auth on localhost:8000** (`~/.cicada/api_token`; `CICADA_API_AUTH=off` for tests) — G49 P0. Gemini/Copilot adapters = one file each, later. → feeds **G49** (engine ladder consumes these connections), **G51**. | ✅ (branch feat/provider-connections — bearer auth 38aba1a, secrets 9c90b1d, adapters ec3c00d/55c9915/a678f80, registry+API 5591a6f, app c5e3ace/13c0d82) |
| G51 | **Consumption / traceability dashboard — minimal + advanced, GitHub-style calendar, `/stats`-style stats, honest pricing** | Append-only JSONL **ledger** at `~/.cicada/telemetry/events-YYYY-MM.jsonl` (never in a bank/git), fed at one seam: `providers.resolve_llm_fn` (timing, `usage`, litellm `response_cost`, list-price `equiv_cost_usd`; **the four remaining direct-litellm callsites — extraction, disambiguation, enrichment, `/ask` — get rerouted through it = G49 P4 seam completion pulled forward**), plus `sleep_run` events in `_finalize` (commit hash, duration, counters) and `agentic_write` events in MCP `cicada_write_claim`; G49 engines emit through the same `record()`. Aggregation merges the ledger with `Cicada-Author` git history (memory writes per day) → `GET /consumption/summary|calendar|stats|connections|harness`. App: **Usage** page (Provenance) — **minimal**: tiles (cost / memory writes / tokens / streak) + 53-week heatmap with tooltips + day drill-down; **advanced**: per-connection cost cards, Swift Charts (tokens/day, cost/day vs API-equivalent, hour-of-day), by-model/stage/bank tables, `/stats`-style facts (lifetime tokens, favorite model, peak day, longest sleep run), optional harness panel from `~/.claude/stats-cache.json` + newest Codex `rate_limits` snapshot (labelled as the harness's own data). **Honesty rules:** subscription = flat `$/mo` + "≈ $X at API list price — estimate, not billed"; usage = real per-model $; local = free; no Claude rate-limit % (no compliant source) — throttle events observed by Cicada instead; no invented token budgets (G49). Adds the first Swift test target (`CicadaAppTests`) for formatting/layout/decoding. → extends **M3/A2** (contributors), **G9** (origins), **G49**; depends on **G50** for plan/price. | ✅ (branch feat/consumption-dashboard — 4959cd5..4c41325 + docs; G49-P4 seam completion shipped) |
| G52 | **"Ask your memory anything" inside the app (NL question → NL answer with wikilink citations)** | An in-app search mode that sends a natural-language question to the existing `POST /ask` (`ask_service`: grounded answer + entity-level citations + explicit gaps) and renders the answer as markdown where every cited entity is a **`[[wikilink]]`-style reference** — clickable, opening the entity page (reuse `TranscludingMarkdownView` link resolution), with the gap analysis shown honestly beneath ("I don't have information about X"). Same behaviour as `cicada_ask` in MCP clients, but available in the companion app's search bar / a dedicated Ask panel (⌘K → "Ask" tab), with recent questions kept per bank. Needs an LLM → runs on the **G49 engine ladder** (subscription CLI → local → BYOK) and records an `ask` event in the **G51** ledger; keyless degrade = citation-only answer (already implemented in `ask_service`). → relates to **M2** (ask endpoint, D3=BOTH), **A5** (gap analysis), the transclusion layer, G13. | ✅ (be32a34 — ⌘K Ask panel) |

---

## Learnings from Anthropic's Model Hardware Standard (2026-08-29)

Anthropic's MHS research preview (2026-08-27, [announcement](https://www.anthropic.com/news/model-hardware-standard-research-preview)) is a standardized *driver* for physical devices: onboard once (partly by an agent **interviewing** you), auto-generate a natural-language **reference file** with capability tags, make the device **discoverable** in a standard format, expose it over **MCP / CLI / code files**, keep live state in a documented **shared-memory state dictionary** that fresh agent instances coordinate through, enforce **safety limits below the model**, and let the agent **compile what it learned into deterministic scripts** instead of reasoning at every step. It is model-agnostic and will be open-sourced. Structurally this is Cicada pointed at devices instead of a person — a third independent convergence (after gbrain and Basic Memory, now from Anthropic) on "markdown reference files + MCP + progressive disclosure + deterministic layer beneath the model". **Thesis note:** cite as validation of markdown-as-driver, the deterministic-owns-safety split (G10 hybrid decision, trust gate, ambiguity guard, P0 auth = "memory safety limits enforced beneath the model"), and procedural distillation (Stage 4 skills). The four items below are what's worth salvaging.

| ID | Item | Notes | Status |
|----|------|-------|--------|
| G53 | **Live state dictionary — the context passport as a runtime object** (Rodrigo agreed 2026-08-29) | Cicada has raw episodes and consolidated entities but no small, documented **live** context object. MHS's state dictionary — "each device described and onboarded once, its variables, controls and sensor values recorded in a single dictionary in shared memory, in a documented format", which *fresh* agent instances read to coordinate — is the missing awake-state layer. Build `memory/_state.md` (YAML frontmatter + short body, regenerated deterministically — zero LLM — by structural Sleep and on every relevant write): active bank; connections + engine in use (G50); current/active projects (top-N by recency/confidence) with their repos' live branch state (repo-link layer); open tasks/ideas (G13) and pending inbox count; recent conversations with resume handles (G48); last Sleep + queue depth; the user's standing preferences (skills). Documented schema so *any* harness reads it in one file at session start: the G49 SessionStart primer hook injects it; `cicada_recall` returns it in `cicada-hints`; Codex/other harnesses read it via AGENTS.md pointer. Not a cache of entity pages — a **cursor into them** (ids + one-liners + wikilinks), so it stays small. → extends `_index.md` (cold-start MoC) with a *now* view; relates to G48, G49 (primer hook), G13, G50, context-passport roadmap. | 🔲 |
| G54 | **Onboarding interview → seed the graph** | Cold-start: a new user without chat exports opens an empty graph. Copy MHS's "chat to an agent that interviews you about your setup" — a first-run **interview** step in the G49 wizard (or `cicada-librarian` prompt in the user's own agent session): who you are, current projects (+ repo paths → `repos:` links), the people/tools around them, standing preferences → written as `user_stated` claims through the existing trust-gated `write_claim` path (so seeds are the highest-trust tier and never clobbered by later extraction). Ten minutes of conversation gives a non-empty, correctly-typed graph on day one; re-runnable later as a "refresh interview" surfacing decayed entities ("still working with X?"). → relates to G49 wizard, G13, G53 (the interview populates the state dictionary too), A4 (skills). | 🔲 |
| G55 | **Executable skills — procedural memory that can carry a script, under R2 governance** | MHS: "Claude packaged what it learned into code files, writing a deterministic script that let it align the laser without having to reason at each step." Cicada's `skill` entities are prose preferences today (A4). Let a skill optionally carry an **executable procedure** (a fenced snippet or a path under `memory/_procedures/`, with declared inputs/outputs, the harness it targets, and last-verified date), produced when Stage 4 detects a *repeated multi-step workflow* rather than a preference. Governance is mandatory the moment a skill can run: R2's **failure ledger + bounded, gated rewrites** (skills never self-edit; a failed run writes a ledger entry and an inbox item; the user confirms rewrites), version in git as today. Surfaces: skill page renders the procedure; `cicada_recall` hints include "there is a procedure for this"; Claude Code/Codex skills can be *generated* from them (SKILL.md export) — the memory system as the source of the user's agent skills. → relates to A4, R2, G49 (skills shipped with the plugin), Stage 4. | 🔲 |
| G58 | **Sync engine — Linear-feel companion app + backend hot-path fixes** (Rodrigo 2026-08-30: "snappy like Linear, its sync engine is so good") | Measured 2026-08-30 on the real bank: `/search` 5 s (the embedding model is re-loaded from disk on every request), `/status` 0.6–0.8 s and `/origins` 1–3 s (every episode/entity re-parsed per call), every tab switch refetches with spinners (per-view `@State` view models), bank switch / post-Sleep = full 1.5 MB graph reload re-serialised on the main actor, 18/20 mutations wait-then-refetch. Design: [`../superpowers/specs/2026-08-30-sync-engine-design.md`](../superpowers/specs/2026-08-30-sync-engine-design.md), plan [`../superpowers/plans/2026-08-30-sync-engine.md`](../superpowers/plans/2026-08-30-sync-engine.md). **Backend:** `bank_index` (mtime/size-keyed frontmatter cache), memoised + pre-warmed embedding model, `GET /sync/version` (mtime + git-HEAD vector, <10 ms) and `GET /sync/events` (SSE), ETag/304 on the big GETs, graph nodes carry `summary` + `content_hash`, blocking work off the event loop. **App:** one `Store` of per-domain `Snapshot`s hydrated from `~/Library/Application Support/Cicada/cache/<bank>/` before the first frame, `SyncEngine` (SSE with polling fallback) refreshing only changed domains with `If-None-Match`, view models as projections (never blank), `Mutation` protocol with optimistic apply + rollback toast, graph **delta** pushes to d3 (positions preserved), instant detail cards from node summaries, sidebar Buttons with ⌘1–9 + accessibility, cached logos, ⌘K Ask panel (G52). Targets: `/status` <30 ms, `/search` <200 ms warm, tab switch same-frame. → relates to G49 (SessionStart primer reads the same version vector later), G53 (state dictionary = a domain of the same store), G51 (dashboard reads through the Store). | ✅ (branch `feat/sync-engine` — 14f5709 841bcaf 90ad9a2 db48a61 92bdad6 861f6af a050feb 5244aa9 49f9f74 9b917eb be32a34 efc2f7a b39b651; measured under live uvicorn: `/status` 620→9 ms, `/origins` 1000→21 ms, `/search` 4800→30 ms warm, `/sync/version` 11 ms, `/graph` 304 in 11 ms — all §8 targets met) |
| G57 | **Telegram webhook per-request secret** (surfaced by the G50 final review) | With bearer auth on every other route (G50), `POST /capture/telegram` is now the one unauthenticated write path into memory: `api/routers/capture.py` only checks that `CICADA_TELEGRAM_BOT_TOKEN` is *configured*, never anything about the request. Fix: register the webhook with `setWebhook?secret_token=<random>` (stored in `~/.cicada/secrets.env`), compare the `X-Telegram-Bot-Api-Secret-Token` header on every request (constant-time), 403 otherwise; update the synced-apps setup copy. Pre-existing gap, small (S). → relates to G29, G50, G49 P0. | 🔲 |
| G56 | **Cicada as the memory layer for MHS-style lab/robot agents** (post-thesis, opportunistic) | MHS gives agents hands, not memory — its own stated limits are memory-shaped ("did not yet understand the underlying physics of the failure", "didn't know how to troubleshoot"). What's missing is consolidation of *experiment history*: which parameters worked, which failures recurred, what a human did to recover. All of it maps onto existing Cicada machinery with no new architecture: **MHS reference file → `tool` entity** importer (device capabilities as an entity page, `source: mhs`), **state-dictionary snapshots / run logs → episodes** emitter (R6 connector pattern, `origin: mhs`), Sleep produces **problem-log claims** (G4 "we solved this by X"), device ↔ project ↔ person edges, temporal decay over device state, and G55 procedures for recovery routines. Thesis framing: Cicada = hippocampus to MHS's motor cortex. Gated on MHS access (research preview by application at modelhardwarestandard.com; open-source later) and on Rodrigo's robotics follow-up work. → relates to G4, G22 (media/video entities for lab cameras), G55, R6. | 🔲 |

---

## Inbox quality, entity logos, capture UX & onboarding walkthroughs (Rodrigo — 2026-08-30)

Five items Rodrigo raised after living with the merged sync engine for a day. Numbered in the
order he wants them tackled.

| ID | Item | Notes | Status |
|----|------|-------|--------|
| G60 | **Conflict resolution, Claude-Code style — time-aware, deduplicated, and "none of these" is an answer** (bug: two open "where does Rodrigo work" conflicts offering `mongodb` vs `supahost` when neither is current) | Today's conflict cards are wrong in four ways. **(1) No dedup:** `inbox_generator.py` never checks for an open conflict on the same entity+predicate, so every Sleep re-writes the same question (`_conflict_nudge` in `claim_reconciler.py`, `resolve_and_prune` in `conflict_resolver.py`). **(2) Time is ignored:** the item carries only `created_date` — not when each competing claim was last observed — even though the thesis says absence of mention is a signal; a `works_at` claim silent for 4 months should be *presented* as stale, and a fresh hint in conversation should refresh/close the conflict, not spawn a third. **(3) The answer set is closed:** option A / option B / "both are true" — no "neither, here's what's true now", no free text, no "ask me later". **(4) Resolve is lossy:** `_resolve_conflict` feeds the button label verbatim into an LLM body rewrite and ignores `claim_id`/`existing_claim_id`, so no claim is superseded/closed. **Design (mirrors Claude Code's `AskUserQuestion`):** every conflict/clarification item carries a *question object* — `question`, `options: [{label, description, claim_id, observed_at, last_referenced, age_days}]`, `allow_other: true`, `allow_defer: true` — with the question text and per-option descriptions written by the model at generation time (template fallback), including the age ("last mentioned 4 months ago"). App renders like `AskUserQuestion`: option rows with descriptions + a free-text "Other…" row + "Not sure / remind me later"; the model may also ask a short follow-up in-thread. Resolve semantics: picking an option **supersedes** the losing claim (bi-temporal close, `valid_to`), "both" keeps both with a `context` qualifier, free-text writes a `user_stated` claim (highest trust) and closes both, defer bumps `remind_after`. Dedup key `(entity_id, predicate)` with **merge-on-collision** (a new competing value joins the open item as another option instead of a new file). Time-aware refresh: Stage 3 re-scores open conflicts each Sleep — an option's claim re-mentioned since the item was created gets its `last_referenced` bumped and surfaces first; an open conflict whose entity/predicate the user *organically* clarifies in conversation is auto-resolved (path 1 of the three resolution paths). Same question-object shape extends to `clarification` and `merge_suggestion` kinds so the card UI is one component. → fixes the Inbox MVP §2/§3, relates to A3/R2 (claim layer), G53, temporal decay, and the `cicada_check_nudges` MCP surface (agent-initiated path gets the same object). **Shipped 2026-08-30:** question objects (`inbox_questions.py`), `(entity, predicate)` dedup with merge-on-collision (`inbox_generator.find_open`), `refresh_open_questions` in Stage 5.56, claim-aware resolve + defer (`inbox_service`), `QuestionView`/`QuestionSelection` in the app, `cicada_resolve_inbox` on MCP. | ✅ |
| G61 | **Update sources for facts — "where to look this up" as a first-class reference on entities & claims** | A contributor (model *or* user) can attach **sources** to a fact: a URL, a file, or a plain-English instruction ("my LinkedIn profile has my current job", "the `about` page of the company site lists the team"). Stored as a `sources:` frontmatter list on the entity (`{ref, kind: url|path|note, predicate?, added_by, added_at}`) and optionally on individual claims — distinct from `source_episodes` (provenance of *where a belief came from*) and from the `## Links` body section (loose bookmarks): a source is a **cheat-sheet for refreshing** a specific fact. Uses: (a) Stage 3 conflict scoring consults sources before asking — if a `works_at` conflict has a LinkedIn source, the model can propose "your profile says X" as the leading option, or resolve silently when trust rules allow; (b) the app's entity page shows sources with an "add source" row (URL or free text) and a "check now" action (`POST /entities/{id}/sources/check` → fetch → LLM compare → claim proposal via the inbox, never a silent overwrite); (c) `cicada_write_claim` accepts `sources=[…]` so a model can record "user told me to check <url> for this" mid-conversation. Fetching is keyless and rate-limited; private pages simply stay `note`-kind reminders the user acts on. → extends G60 (conflict inputs), M3/A2 (contributors), G9 (origins), G22/G30 (media & links). **Shipped 2026-08-30 (minimal slice):** `sources:` frontmatter via `api/services/fact_sources.py`, `GET/POST/DELETE /entities/{id}/sources`, `cicada_write_claim(sources=)`, the conflict-card `hint`, and the app's entity Sources section. Fetching/"check now" remains a follow-up. | ✅ |
| G59 | **Entity logos — Revolut-style circular avatar next to the name** | Detect a logo for entities that plausibly have one (`company`, `tool`, some `project`/`media`) and render it as a circle beside the name in the detail card, inbox cards, search results and (optionally) as a canvas image on graph nodes. **Resolution ladder, keyless:** explicit `logo:` frontmatter → domain from the entity's `sources:`/`## Links`/`media.url` → domain guess from the name (LLM-free heuristics first: `mongodb` → `mongodb.com`; LLM only at Sleep for ambiguous names, recorded as a `website` claim) → favicon/touch-icon fetch (site's `apple-touch-icon` / `link rel=icon`, DuckDuckGo icon service as fallback) → cached PNG under `~/.cicada/logos/<entity-id>.png` (never in a bank) served by `GET /entities/{id}/logo` (ETag, 404 = monogram fallback in the app). Refreshed lazily (30-day TTL) so an updated brand mark shows up. App: `LogoImage` grows a remote/monogram mode (initials on the entity-type color when there is no logo, same size), avatar in `EntityDetailCard` header and `InboxCardView` title row. → relates to G58 (cached logos), G22 (media thumbnails), G61 (domain from sources). Shipped: api/services/logo_service.py (ladder + keyless fetch + ~/.cicada/logos/<bank>/ cache, 30 d hits / 7 d misses), GET /entities/{id}/logo, has_logo on graph nodes, a warm_logos Sleep tail step, LogoImage's entity mode (circle + monogram fallback) in the detail card / inbox / clusters / Ask chips, and an off-by-default "Show logos" graph toggle. | ✅ |
| G62 | **Capture page — show only what's connected, "+" to add (Revolut-style)** | The Capture page (`SourcesView.swift`, 1,341 lines) explains every channel up front: Import tiles, an RSS section with sample URL, a Calendars section with sample URL, Synced apps prose, origins strip, queue. Redesign: a single **"Connected"** list of the channels that actually have state (subscribed feeds, subscribed calendars, bookmark sync last run, Notes sync last run, Telegram if configured, chat-export imports by harness) as compact rows with a status line ("3 feeds · polled 2 h ago") and a row-level ⋯ menu (poll now, remove), plus one **`+` button** that opens a picker sheet of everything addable (Chat export, Bookmarks file, RSS feed, Calendar, Paste URL, Chrome/Safari bookmarks, Apple Notes, Telegram) — each with a one-line description *inside the sheet*, not on the page. Empty state = the queue card + a single "+ Add a source" call to action. Needs a small backend addition: `GET /sources/channels` (or fold into `/sources`) reporting per-channel connected state + last-sync timestamps so the page stops inferring connection from transient button results. → relates to G30, G29 (Telegram), M7, G9 (origin pills stay, but under the list). Shipped: GET /sources/channels derived from persisted state only (registries, sync_state.json, origin counts, the Telegram env flag), a channels sync domain, a Capture page that lists only connected channels with per-channel ⋯ actions, and an AddSourceSheet ("+", ⌘N) that owns all the explanatory copy. SourcesView is 1,341 → under 450 lines. | ✅ |
| G63 | **Connections page clarity — what "Claude plan · Connected" means, and Connect vs Connections** | Rodrigo: "I don't get how Claude is connected." The card says *Connected* because `claude auth status --json` reports a claude.ai login for the Claude Code CLI on this Mac — but the page never says that. Fix the copy per card: a one-line "how" under the plan ("Signed in through Claude Code on this Mac — Cicada uses your plan through the `claude` CLI, never the token"), the tier picker only when the plan is Max and labelled as a *price estimate* preference, and an explicit "what this powers" line (Sleep extraction, Ask, clarifications). Rename to remove the Connect/Connections collision: sidebar **Connect** → "**Agents**" (wire your harnesses into Cicada via MCP) and **Connections** → "**Plans & keys**" (what Cicada bills against), with matching page subtitles. → relates to G50, G49 (engine ladder copy), G51 (price estimate wording). Shipped: ConnectionStatus.how (authored next to each adapter's probe) and .powers (assigned by the registry's engine selection); sidebar Connections → "Plans & keys" and Connect → "Agents" with AppTab raw values unchanged; the Max tier picker relabelled "Your Max tier (for cost estimates only)" and shown only for Claude Max. | ✅ |
| G64 | **Import walkthroughs — zoomed-cursor step videos + "open the export page" buttons** | For each export-based source (Claude, ChatGPT, Google Takeout/YouTube, Instagram, Chrome/Safari bookmarks) ship a short looping screen recording with a zoomed cursor showing exactly where the export lives, embedded in the `+` picker (G62) next to a button that deep-links to the vendor's settings page (`https://claude.ai/settings/data-privacy-controls`, `https://chatgpt.com/#settings/DataControls`, `https://takeout.google.com`, Instagram *Your information and permissions → Download your information*) and a "then drop the file here" target. Recordings live as bundled `.mp4`/`.gif` under `Resources/walkthroughs/` (re-recorded when a vendor moves the setting; keep them under ~2 MB each). Prereq: a repeatable recording recipe (Screen Studio or `screencapture -v` + a cursor-zoom pass) documented in `docs/`. → relates to G62, M7 (import parsers), onboarding/G54. Shipped (buttons + steps): a WalkthroughPanel in the "+" sheet with a Claude/ChatGPT/Takeout/Instagram picker, 3–4 numbered steps, an "Open <vendor> export settings" button, and a reserved 16:9 area that plays Resources/walkthroughs/<vendor>.mp4 when one exists. Recording the clips is a separate manual pass — docs/walkthrough-recording.md. | 🔲 (buttons + step lists ✅ this branch; recordings still need a screen-recording session) |
| G65 | **Feed data quality — media entity-id collisions, consent-page junk, real query relevance** (found tracing the 2026-08-31 Feed bugs) | Three backend follow-ups behind the shipped UI fixes. **(a) Entity-id collisions:** `media_ingestor._media_entity_id` slugifies the page *title*, so 148 distinct bookmarks ("Before you continue to Google Search") share one entity page; append the URL-hash suffix whenever the slug already exists for a different normalized URL, not only when >120 bytes, + a one-shot migration for existing collisions. **(b) Consent/cookie-wall junk:** those 148 saves are Google consent interstitials, not content — detect (title/URL patterns) at ingest, fetch through or mark `status: dropped`, and sweep existing ones. **(c) Real relevance:** the Feed badge shows §3.4 decayed confidence, constant ≈57% after a bulk sync (identical defaults, `personal_relevance_weight` never written); either wire the search query into a vector-index score server-side or vary the inputs (per-item `last_referenced` bumps on open, weight from Sleep). UI side shipped 2026-08-31: unique row identity (`entityId|url`) fixing the blank-gap rows, badge hidden while rendered percentages are uniform. | 🔲 |
| G66 | **Decay classes — evergreen/durable/active/volatile, agent-estimated, user-overridable** (Rodrigo 2026-08-31: "I don't see why bookmarks would need to get decayed"; "unlimited as an option") | Spec [`2026-08-31-decay-policy-and-history-diffs-design.md`](../superpowers/specs/2026-08-31-decay-policy-and-history-diffs-design.md) §1: semantic `decay_class` beside the numeric rate, one resolver (`decay_policy.py`), Stage-1 estimates the class but may never emit `evergreen` (anti-pollution rail), both decay engines honor it (claim engine gets a class multiplier), re-mention finally *restores* confidence/status (the promised recovery path never existed), `PUT /entities/{id}/decay`, decay chip + picker in the entity card, one-shot backfill (media→evergreen, skills→durable). **Shipped 2026-08-31:** `DecayClass` + `DECAY_CLASS_RATES`/`CLAIM_DECAY_MULTIPLIERS`/`AGENT_PRODUCIBLE_DECAY_CLASSES` in `schemas.py`; the one resolver `api/services/decay_policy.py`; every writer (media/skills/Sleep-create/agentic/clarification) through it; Stage-1 estimates a class behind the evergreen rail; `conflict_resolver` skips evergreen and promotes back on re-mention; `claim_reconciler` multiplies decay by the subject's class; `PUT /entities/{id}/decay`; `decayClass` on `EntityResponse` + graph nodes (folded into `content_hash`); the decay chip + picker in `EntityDetailCard`; and the one-shot `decay_migration` backfill on startup. | ✅ |
| G67 | **Commit-diff views — GitKraken-style added/removed lines on entity history + contributor click-through** (Rodrigo 2026-08-31) | Spec §2: backend `GET /entities/{id}/history/{commit}/diff` already shipped; add `GET /contributors/commits?author=`; app gets a shared `DiffView` (green/red, monospaced, gutters) — tappable commit rows in the entity History tab, contributor→commits→entity-chip→diff drill-down. **Shipped 2026-08-31:** `git_service.get_contributor_commits` + `GET /contributors/commits?author=&limit=` (author as a query param — model ids contain slashes), a shared `DiffView` with a pure testable `DiffModel` (`Views/Common/DiffView.swift`), tappable commit rows with on-demand per-commit diffs in the entity History tab, and the Contributors row → commits → entity chip → diff drill-down. | ✅ |
| G68 | **UI round 2 — 6-row sidebar + Settings scene, Capture→Feed and Contributors+Usage→Activity merges, audit top-10** (Rodrigo 2026-08-31: "side panel congested and repetitive") | Spec [`2026-08-31-ui-round-2-design.md`](../superpowers/specs/2026-08-31-ui-round-2-design.md), grounded in the six-lens audit workflow: sidebar 10 tabs/5 labels → 6 rows + footer gear (native Settings scene hosts Agents + Plans & keys), Capture merges into Feed, Usage+Contributors merge into Activity, plus the entity-card cross-entity state-bleed fix, AddSourceSheet vendor-wiring fixes, Usage render stabilization, semantic color tokens, copy normalization ("Rodrigo"→"You"), channel-row discoverability, state-coverage batch. **Shipped 2026-08-31:** sidebar is 6 rows + footer gear + a native `Settings{}` scene (Agents, Plans & keys); Capture merged into Feed (channels strip + `+`/⌘N) with its queue card on Sleep; Usage + Contributors merged into Activity with the origins strip; `CicadaTheme.success/warning/danger/info/codeBackground` replaced every state hex (grep-tested); one `Copy` enum owns cross-page pointers and subtitles ("Rodrigo" → "You"); `.id(entity.id)` killed the entity-card state bleed; AddSourceSheet tiles now offer only the vendors they can upload; Usage range switches cancel-and-guard; Ask/heatmap/Inbox/Contributors gained real list ids and loading states. | ✅ |

---

## Open decisions (asked to Rodrigo — answers recorded here)

These are the foundational forks; most of the backlog hangs off them.

- **D1 — Storage backend.** Stay markdown+git+LEANN? Move toward Postgres+pgvector (Honcho/gbrain)? Hybrid (markdown = source of truth, pg = index)? — _awaiting_
- **D2 — Entity model philosophy.** Keep closed 8-type set + promotion gate? Move toward Honcho-style emergent/belief/observer-observed (drop promotion)? Hybrid (entities + per-context dimensions)? — _awaiting_
- **D3 — Retrieval interface.** Add a natural-language `ask`/dialectic endpoint (agent queries memory in NL)? Keep direct file traversal? Both? — _awaiting_
- **D4 — Peers & multi-bank scope.** Build peers (humans/agents/robots equal) + multiple memory banks as a near-term feature, or research-only for now? — _awaiting_

> Answers (2026-06-16):
>
> - **D1 (storage): DECIDED (2026-06-17)** — markdown+git stays the source of truth; **add a derived embedding index, and Rodrigo is willing to go straight to Postgres+pgvector** (rather than sqlite-vec first) so pgvector + derived indexes land directly, then the ask endpoint. Research recommended sqlite-vec-first for a single-user bundle; the Postgres-direct path is viable because the index is *derived/rebuildable* — see dossier §D1 for the tradeoff. LEANN is being replaced either way.
> - **D2 (entity model): research-only** — no commitment yet; R4 + R7 findings inform it. Keep closed types + promotion for now.
> - **D3 (retrieval): BOTH** ✅ — add a natural-language `ask`/dialectic endpoint (answer + git-blame citations + gap analysis) AND keep direct file traversal. → unblocks A5; new design item.
> - **D4 (peers + multi-bank): research-only** — design the peer (observer/observed) model + multi-bank "memory projects", don't build yet. R8 informs it.

**Consequence of D3 = BOTH:** the `ask`/dialectic endpoint is now a committed design item
(not just research). It folds in A5 (gap analysis) and the Honcho/gbrain "answer not pages"
insight. Spec to be written once R1/R7 land. Everything else stays research-gated.
