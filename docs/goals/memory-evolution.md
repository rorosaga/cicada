# Goal: Memory Evolution (improvement wave)

Backlog distilled from Rodrigo's notes (2026-06-16). Triaged into three tracks:
**APPLY** (buildable now, low architecture risk), **RESEARCH** (needs investigation —
findings land in [`../inspiration/research/`](../inspiration/research/)), and **DECIDE**
(needs Rodrigo's call before work proceeds — see "Open decisions" at bottom).

Status legend: 🔲 todo · 🔬 researching · ❓ awaiting decision · 🛠️ in progress · ✅ done

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
  - **Deferred to M5f (clear TODO in `sleep_cycle`, Stage 5.57):** the link-enrichment subagent
    (John → recommended websites: fetch + summarize a link with no conversational description). M5e is the
    claim/trust/retrieval core only.
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
    - **Scope correction.** The M5e commit subject ("wire claim layer into Sleep") over-stated the
      consolidation half: `reconcile_stage3` / `entities_to_claims` are implemented, fully tested, and
      load-bearing in **retrieval**, but the live Stage-3 still runs the legacy `resolve_and_prune` and
      live Stage-5 still emits claims only via the M5b seeder, not the reconciler. Replacing the legacy
      Stage-3 body with `reconcile_stage3` end-to-end is **deferred to M5f** (tracked, not assumed done) —
      a larger pipeline swap kept out of this review-fix pass to avoid regressing the entity-extraction
      path. The human-protection invariant is now enforced in the live path at the **prose** level (fix 1);
      the **claim** level lands when Stage-3 is swapped in M5f.

## APPLY — buildable now (low architecture risk)

| ID | Item | Notes | Status |
|----|------|-------|--------|
| A1 | **Per-commit diff view in node history** | Expand entity history to show added-vs-removed (git diff per entity per commit). Builds on existing `/entities/{id}/history`. | ✅ |
| A2 | **Contributors view** | Which LLM model wrote which contribution to memory. Record model id in Sleep commit metadata/trailers; surface a "contributors" view + per-node attribution. | ✅ |
| A3 | **Animated bookworm on ingestion page** | Reuse the menu-bar tamagotchi sprite/state machine on the conversation-upload/ingestion screen. | 🔲 |
| A4 | **Enrich `skill` entity capture** | Store "Rodrigo usually asks to do X a certain way" (e.g. FastAPI project layout & repo structure conventions). Procedural-preference skills. → ties to D2/D5. | 🔲 |
| A5 | **Explicit gap analysis ("I don't know")** | Retrieval/answer surface admits what it does NOT know (no edge between X/Y, low confidence, stale `last_referenced`). Endorsed by both Honcho & gbrain notes. → ties to D3. | 🔲 |

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
| G1 | **Multiple memory banks / "memory projects"** (→ **M6, committed, next-up**) | Several named memory banks so the live consolidated graph is never erased: a **project dropdown in the Memory/graph page** to switch the active bank; **save the current graph under a name**; **create a new (empty/seed) bank** to test against (e.g. a bank seeded from imported chat exports + the big-model M5d consolidation). Backend: a banks registry + `memory_path` resolves to the active bank (legacy `memory/` = the default bank); `GET/POST /banks`, activate, duplicate-as-name. Banks can cross-reference. → ties to D2/D4/G12. **Rodrigo confirmed: build this now, before reviewing the demo surfaces.** | 🔲 |
| G2 | **Extend entity taxonomy** | New types: website/bookmark, research paper, idea, project-note, recipe, song/media, … Reference e.g. a song on another entity's wiki page with a personal-relevance note. → gated by D2. | ❓ |
| G3 | **Bookworm "feed" knowledge page** | Sync-driven feed (bookmarks first), each item an entity with summary + *personal* relevance. Filterable view across articles/bookmarks/songs by a **relevance metric**. | ✅ (M4 — RSS connector + `GET /sources?sort=relevance` + `FeedView`; `personal_relevance` frontmatter added, read-only for now) |
| G4 | **Problem-log entity sections** | "We solved this problem by doing X" + open-ended "we discussed this — how did it end up going?" Likely sections under project/concept entities. | 🔲 |
| G5 | **"Project improvements" sections** | Things discussed to improve on a given project. Probably a section grammar under `project` entities. | 🔲 |
| G6 | **Entity-type audit interface** | A way to easily audit which entity types exist and structure info per type (section grammar per type). Meta-tooling over the taxonomy. | 🔲 |
| G7 | **Reduce Rodrigo-node centrality** | "Rodrigo" is over-central; introduce more intermediate hub/bridge nodes. Overlaps v2 hubs work. | 🔲 |
| G8 | **Agent-research memory + opinions** | Memory of agents' work (e.g. the Honcho mini-research, with raw traces). A second agent can add an *opinion* → two versions of the same memory side by side (observer/observed). → ties to D4/R8. | ❓ |
| G10 | **Bulk re-extraction under the new architecture (big model)** | Re-run entity/claim extraction over the **full Claude.ai + ChatGPT conversation export corpus** (as Rodrigo did once before) but with the **new D2 claim-layer architecture** in mind, using a **big/high-quality model** (planned: buy OpenRouter or similar credits). Quality goals: (1) **richer, more detailed per-page summaries** (the current pages are critically thin — median ≈50 words); (2) **avoid nonsense single-mention entities** (graph pollution — handled by the new `activation`/candidate gate, not a hard count); (3) surface **better intermediate/abstraction concepts** that encapsulate many things (intermediate "in-between" nodes — relates to G7 Rodrigo-centrality + hubs + abstract cross-links). This **IS the D2 migration's full-backfill / re-consolidation step** — but done deliberately for *quality*, not the cheap lazy path. **Design fork to decide: extraction engine.** (a) **Python Sleep cycle** (current) — deterministic, has the 5 structured stages (resolution/conflict/decay/index), but extraction is a single structured litellm call per episode. (b) **Claude-Code-driven agentic extraction** (Rodrigo's idea) — a Claude Code *workflow/skill* reads an episode batch and writes to the graph via the MCP Bookworm tools, giving a big reasoning model full agentic latitude to write rich pages + choose intermediate concepts (and dogfoods the agent-facing write path; pairs with G9 `origin: claude-code`). Tension: (b) is richer but less deterministic/idempotent and may skip the structured resolution/decay logic. **Likely best = hybrid:** agent does the rich extraction/summarization + concept abstraction; the deterministic pipeline still owns dedup, contradiction (bi-temporal close), decay, and indexing — i.e. the agent writes *claims* through MCP tools that enforce the structure. → gated by D2 final architecture; feeds the M5 migration build plan. | 🔲 |
| G9 | **Cross-harness episode sync + origin provenance** | Two linked parts. **(a) Sync queue:** a standardized way for *any* agent harness — Claude Code, Codex, Cursor, OpenCLAW, ChatGPT/Claude exports, future personal-agent harnesses — to push its conversation episodes into a queue that feeds Cicada's `episodes/` inbox. Each harness is a thin "episode emitter" (same principle as the M4 media/RSS connectors); options to investigate: MCP `cicada_save_episode` (already exists, MCP-native), harness hooks/stop-hooks that dump transcripts, a file-drop/watch queue, or a small ingest API. Must be source-agnostic and dedup-safe (content hash). **(b) Origin provenance:** record the **origin harness** of each episode/memory as a first-class provenance dimension — *distinct from the M3 contributor*. M3's `Cicada-Author` trailer answers "which **model** wrote this memory"; G9 answers "which **harness/client** the memory **originated from**" (e.g. `origin: claude-code`). Propagate `origin` from episode frontmatter → entities/claims (via `source_episodes`) → a contributors-style view filterable by harness. The episode `source` field is a partial foundation; this makes origin a tracked, end-to-end, queryable dimension. → relates to M3 (contributors), R6 (connectors-as-emitters), D2 (claim/observer model: `origin` pairs naturally with the `observer`/`source_trust` fields in the new architecture). | 🔲 |
| G11 | **In-app media preview (images · videos · websites) + artifacts as memories** | Preview rich media **inside the app**: **images** (inline + lightbox), **videos** (inline player / thumbnail-to-play), and **website link previews** (Open-Graph card or a small embedded web view of saved bookmarks/URLs — reuse the M4 media-ingestion OG enrichment for the card; a `WKWebView` for full preview). Let media-as-artifacts be **saved as memories** — an image/video/site embedded in an entity or claim, rendered inline like the transclusion layer renders embedded pages. Extends the inline-transclusion model (`![[…]]`) to media embeds (D2 transclusion currently excludes images/media — revisit) and the M4 `media` entities (which already store `url`/`thumbnail`/`media_type`) gain real in-app previews instead of just opening the URL. Sources: chat-export images (Gemini takeout), saved bookmarks/YouTube/articles, pasted/diagram artifacts. → **underpins G14** (mood-boards are media-preview-heavy); relates to G2 (media types), G3/M4 (feed), the transclusion layer, M5c surfaces. | 🔲 |
| G12 | **Chat-history import queue (export → bank, date-preserving)** (→ **M7, committed, next-up**) | A UI + pipeline to **import past chat exports** (Claude `conversations.json`, ChatGPT export, Gemini `MyActivity.html`) — from the bookworm/ingestion panel **or a settings page** — and **consolidate them into a chosen bank: new or existing** (ties to G1/M6). **Must preserve original conversation dates** extracted from export metadata (Claude per-message/per-conversation `created_at`; Gemini activity timestamps) so the consolidated timeline is historically accurate — open question whether dates are reflected via backdated episode frontmatter / git-history (rebased) / a purely additive layer; **decision: backdate episode frontmatter to the real `created_at` (the Sleep pipeline + claim `valid_from` already key on dates), additive — don't rewrite git history.** Same export path Rodrigo uses manually today; this productizes it. Data staged outside the repo at `…/thesis/cicada-data/chat-exports/` (claude = `conversations.json` 29MB w/ dates ✓; gemini = `MyActivity.html` + images; openai = TBD). → feeds M5d (the big-model consolidation runs on these imported episodes into the new bank). → relates to G9 (origin: claude-export/chatgpt-export/gemini-export), G10/M5d. | 🔲 |
| G13 | **Application-wide tasks/ideas backlog (personal-assistant memory)** | Make the per-project backlog of **tasks / ideas / open-questions** a first-class **in-memory** artifact — the kind currently hand-annotated in this very file — captured from conversation, scoped per project/bank, surfaced proactively, and resolvable. Model as **claims** (`predicate: todo \| idea \| open-question \| improvement`, plus a `status: open \| in-progress \| done \| parked`) or a light task-entity, tied to the related project/concept entity. **Interactions to consolidate it:** (1) quick-capture — menu-bar bookworm "jot" / MCP `cicada_note` / Sleep extraction of actionables ("we should…", "idea:", "TODO"); (2) a per-project **"Tasks & Ideas" list/board view** (open · in-progress · done); (3) proactive surfacing via the **inbox** when a chat touches a related topic ("you had an open idea about X — still relevant?"); (4) a resolution loop where marking *done* writes a G4 problem-log "solved by X" claim, and *park* decays. **Dogfood demo:** this thesis's own backlog (`memory-evolution.md`) becomes a Cicada project/bank. → generalizes G4/G5; uses the inbox + claim/status model + bank scoping (M6). | 🔲 |
| G14 | **Aesthetics / mood-board entities (postponed — captured)** | A first-class **`aesthetic`/mood-board** entity — image-heavy, video/Pinterest links, artifact-like — for storing designs, references, and aesthetics that **recur across projects/ideas**. Rich interlinking: an aesthetic relates to other aesthetics and *influences* projects (Rodrigo's example: **Blade Runner → futuristic cyberpunk → a robot-design project**). A **dedicated gallery/board view** (not the force graph): image grid + embedded links + descriptions, cross-referenced, where Rodrigo captures self-made designs and links them to Pinterest boards / external refs and reuses aesthetics across projects. Like a visual/creative cousin of `skill`. **Depends on G11** (in-app image rendering) + extends **G2** (media taxonomy) + the **transclusion** layer (embed boards/images as `![[…]]`). Postponed per Rodrigo. → relates to G2, G11, transclusion, the claim relationship model. | 🔲 |

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
