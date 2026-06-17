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
  - **Deferred:** **G2** (full media-type taxonomy expansion — research-paper/recipe/song/etc.)
    stays gated by D2 — left as a labeled TODO. Live `feedUrl` network fetch is implemented but
    flag-gated and untested (offline-by-design). Setting `personal_relevance`/`_weight` from the
    app (the §3.2 write path) is read-only for now.

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
| G1 | **Multiple memory banks / "memory projects"** | Several versioned memory banks for re-consolidating past conversations (another model, or parallel ongoing banks for testing). Banks cross-reference. → ties to D2/D4. | ❓ |
| G2 | **Extend entity taxonomy** | New types: website/bookmark, research paper, idea, project-note, recipe, song/media, … Reference e.g. a song on another entity's wiki page with a personal-relevance note. → gated by D2. | ❓ |
| G3 | **Bookworm "feed" knowledge page** | Sync-driven feed (bookmarks first), each item an entity with summary + *personal* relevance. Filterable view across articles/bookmarks/songs by a **relevance metric**. | ✅ (M4 — RSS connector + `GET /sources?sort=relevance` + `FeedView`; `personal_relevance` frontmatter added, read-only for now) |
| G4 | **Problem-log entity sections** | "We solved this problem by doing X" + open-ended "we discussed this — how did it end up going?" Likely sections under project/concept entities. | 🔲 |
| G5 | **"Project improvements" sections** | Things discussed to improve on a given project. Probably a section grammar under `project` entities. | 🔲 |
| G6 | **Entity-type audit interface** | A way to easily audit which entity types exist and structure info per type (section grammar per type). Meta-tooling over the taxonomy. | 🔲 |
| G7 | **Reduce Rodrigo-node centrality** | "Rodrigo" is over-central; introduce more intermediate hub/bridge nodes. Overlaps v2 hubs work. | 🔲 |
| G8 | **Agent-research memory + opinions** | Memory of agents' work (e.g. the Honcho mini-research, with raw traces). A second agent can add an *opinion* → two versions of the same memory side by side (observer/observed). → ties to D4/R8. | ❓ |

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
