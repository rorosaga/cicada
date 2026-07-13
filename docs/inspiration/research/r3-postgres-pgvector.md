# Postgres + pgvector vs markdown+git+LEANN

> Research note (R3) for Cicada's storage/retrieval decision (D1, D3). Informs — does
> not decide. Companion to [`honcho.md`](../honcho.md) and [`gbrain.md`](../gbrain.md).
> Scale assumption: personal, ~1,882 entities today, low-thousands ceiling.

## TL;DR

- **Storage is the wrong axis to optimize at personal scale.** LEANN's whole pitch is
  ~50× smaller index via on-the-fly embedding *recomputation*, paying ~2s query latency
  to save megabytes. At ~1,882 entities the raw embeddings would be a few MB anyway, so
  LEANN is solving a problem Cicada doesn't have — while imposing the latency cost, which
  *does* hurt now that D3 commits to an interactive natural-language ask endpoint.
- **The markdown+git layer is Cicada's actual moat and should stay the source of truth.**
  Transparency, provenance via `git blame`, Obsidian compatibility, portability, zero
  infra — none of that comes from the vector index. The vector index is a *derived,
  disposable* artifact. This cleanly separates the two decisions.
- **pgvector buys real query power Cicada will want for D3:** native hybrid search
  (BM25-flavored `ts_rank_cd` / `pg_textsearch` + vector + RRF in one query), SQL filters
  on frontmatter fields, and sub-10ms latency with stored HNSW vectors. Both reference
  systems (Honcho, gbrain) already run Postgres+pgvector. *(High confidence on capability;
  medium on exact latency numbers — vendor benchmarks.)*
- **Recommended: the HYBRID option.** Markdown+git stays canonical; a derived index
  (pgvector *or* sqlite-vec) is rebuilt from markdown by the Sleep cycle. This is exactly
  what gbrain does ("markdown files as system of record, synced to a DB for retrieval").
  It is the lowest-regret path and keeps D1 reversible.
- **For a single-user macOS app, sqlite-vec is a serious alternative to pgvector** for the
  derived index: no daemon, no `Process()`-spawned Postgres, ships in the app bundle.
  pgvector wins on raw feature richness; sqlite-vec wins on infra burden. This is the one
  genuinely open sub-decision (see Open questions).

## Findings

### 1. LEANN: what it actually optimizes (and what it costs)

LEANN (UC Berkeley Sky Computing Lab + CUHK/AWS/UC Davis, [arXiv:2506.08276](https://arxiv.org/abs/2506.08276),
[project page](https://sky.cs.berkeley.edu/project/leann/)) is explicitly *a low-storage
vector index for personal devices*. Headline: index size **under 5% of raw data, up to
~50× smaller** than conventional indexes, **90% top-3 recall in under ~2s** on QA
benchmarks.

The mechanism is the catch. LEANN **does not store the embedding vectors at all** — it
keeps a pruned HNSW-style proximity graph and **recomputes embeddings on the fly at query
time** with the same encoder used at build time ([arxiv html](https://arxiv.org/html/2506.08276v1),
[neovintage write-up: "the vector index that throws out the vectors"](https://neovintage.org/posts/leann-the-vector-index-that-throws-out-the-vectors/)).
Two-level traversal + dynamic batching keep that recomputation from being catastrophic,
but the fundamental trade is **CPU/GPU at query time in exchange for disk at rest.**

The authors are candid about the value prop: *"2 seconds vs 0.03 seconds does not matter
when the model is going to think for 20+ seconds anyway"* (paraphrased from coverage,
[MarkTechPost](https://www.marktechpost.com/2025/08/12/meet-leann-the-tiniest-vector-database-that-democratizes-personal-ai-with-storage-efficient-approximate-nearest-neighbor-ann-search-index/)).
That assumption holds for RAG-into-LLM. **It breaks for an interactive companion app**
where a user clicks a node, types a quick search, or the graph view filters live — there
the ~2s (and the recompute spend / battery) is felt directly, and there is no 20s LLM
turn to hide behind.

**Why this matters for Cicada specifically:** LEANN's 50× storage win is proportional to
corpus size. The CLAUDE.md framing cites "400K chunks = 64MB vs 1.8GB." Cicada has ~1,882
entities and a comparable-order episode count — call it low tens of thousands of chunks at
most. At `text-embedding-3-small` (1,536 dims, 4 bytes) that's on the order of single-digit
to low-tens of MB of raw embeddings *stored*. Saving 95% of a number that small is
irrelevant on a Mac with a 500GB SSD. **Cicada is paying LEANN's latency tax to win a
storage prize it doesn't need.** *(Confidence: high on the reasoning; the exact MB figure
is an estimate — verify with `du -sh memory/leann` and chunk count.)*

### 2. pgvector: state of play (2025–2026)

pgvector adds vector columns + ANN indexes (IVFFlat and HNSW) to Postgres. It **stores
full embeddings** and indexes them, so query latency is low and there is no recompute.

- **Latency at Cicada's scale:** HNSW returns matches in roughly **5–8ms**, with end-to-end
  search ~tens to a few hundred ms once you include *embedding the query* (the network/API
  round-trip dominates, not the index) ([Markaicode production RAG with pgvector](https://markaicode.com/pgvector-rag-production/),
  [Instaclustr pgvector benchmark](https://www.instaclustr.com/education/vector-database/pgvector-performance-benchmark-results-and-5-ways-to-boost-performance/)).
  *(Confidence: medium — vendor/blog benchmarks, not independent. But the order of
  magnitude — single-digit ms index lookup at thousands of vectors — is not controversial.)*
- **Scaling ceiling is far above Cicada:** pgvector HNSW "slows noticeably above 5–10M
  vectors" and needs the index resident in RAM; at 50M+ you reach 150GB RAM territory and
  reach for `pgvectorscale`/StreamingDiskANN ([Vecstore 2026 benchmarks](https://vecstore.app/blog/vector-database-performance-compared),
  [firecrawl 2026 vector DB comparison](https://www.firecrawl.dev/blog/best-vector-databases)).
  **None of this is in Cicada's universe.** A few thousand vectors is trivially in-memory.
- **Hybrid search is a first-class pattern.** Postgres does BM25-flavored ranking via
  `ts_rank_cd` over `tsvector`, and you fuse it with vector cosine via **Reciprocal Rank
  Fusion (RRF)** in a single query. Reported lift: **vector-only ~62% precision → +FTS+RRF
  ~84%** ([DEV: hybrid search in 100 lines](https://dev.to/gabrielanhaia/hybrid-search-in-100-lines-bm25-pgvector-with-rrf-merge-58cn),
  [ParadeDB: hybrid search missing manual](https://www.paradedb.com/blog/hybrid-search-in-postgresql-the-missing-manual)).
  New extensions push true BM25 (not just cover-density): **`pg_textsearch`** from TigerData
  gives real BM25 ranking and a single `search_chunks(query, k)` that fuses vector + BM25 +
  trigram fuzzy with RRF ([TigerData: pg_textsearch](https://www.tigerdata.com/blog/introducing-pg_textsearch-true-bm25-ranking-hybrid-retrieval-postgres)).
  LEANN is vector-only; you'd bolt BM25 on yourself.
- **SQL filtering on metadata** comes free: `WHERE type = 'project' AND confidence > 0.4
  AND status != 'archived'` alongside the vector ORDER BY. With markdown+LEANN, every
  frontmatter filter is hand-rolled file traversal.

### 3. Infra / on-device cost — the real argument *against* pgvector

This is where markdown+LEANN (or markdown+sqlite-vec) wins decisively for a single-user
desktop app:

- **pgvector means running Postgres.** Cicada's design already spawns FastAPI via Swift
  `Process()`; adding a Postgres daemon (plus Honcho-style Redis if you copied that stack)
  is a second long-lived server to install, supervise, migrate, back up, and version on a
  *personal Mac*. That is real onboarding and reliability surface for zero scale benefit.
- **sqlite-vec is the middle path.** `sqlite-vec` (asg017, successor to sqlite-vss,
  [GitHub](https://github.com/asg017/sqlite-vec)) is an **embedded** extension: no daemon,
  runs in-process, ships in the app bundle, "removes the operational burden of a separate
  vector database for local/desktop/embedded" ([AI in Plain English](https://ai.plainenglish.io/embedded-intelligence-how-sqlite-vec-delivers-fast-local-vector-search-for-ai-de6d62936055)).
  Trade-off vs pgvector: fewer/weaker ANN options (brute-force / limited indexing vs
  pgvector's mature HNSW+IVFFlat) and you assemble hybrid search more manually ([DEV: RAG inside RDBMS, sqlite-vec vs pgvector](https://dev.to/jonbiz/implementing-a-rag-system-inside-an-rdbms-sqlite-and-postgres-with-sqlite-vec-pgvector-4d5h)).
  At a few thousand vectors, brute-force cosine in sqlite-vec is *already fast enough* —
  ANN sophistication only matters at scales Cicada won't reach.

### 4. Transparency / provenance / portability — orthogonal to the index choice

The features Cicada's thesis leans on do **not** live in the vector layer:

- **Provenance:** `git blame entities/x.md` → per-line commit → structured Sleep-cycle
  commit message (source episode + trigger). A SQL row has no equivalent unless you build
  an audit-table system that reinvents git. **Keep git.**
- **Transparency / human-readability:** markdown is the artifact the user inspects and
  edits; Obsidian-compatibility and portability are properties of the *files*, not the
  index. A Postgres dump is none of these.
- **This is the key insight:** these properties belong to the **system of record**, and
  the vector index is a **derived, throwaway artifact**. They are *separable* decisions —
  which is what makes the hybrid option clean rather than a compromise.

### 5. Reference systems already validate the hybrid pattern

Both adjacent systems Cicada has studied run Postgres+pgvector — but note *how*:

- **Honcho** (Plastic Labs): FastAPI + **Postgres+pgvector** (messages, peers, sessions,
  embeddings) + Redis for async workers; pgvector *is* the system of record there
  ([GitHub](https://github.com/plastic-labs/honcho), [andrew.ooo review](https://andrew.ooo/posts/honcho-plastic-labs-agent-memory-review/)).
  But Honcho is a multi-tenant server product, not a single-user desktop app — its infra
  burden is amortized across many users. That context does **not** transfer to Cicada.
- **gbrain** (Garry Tan): **"Markdown files as system of record in git repos, synced to a
  DB for retrieval"** with **HNSW + BM25** hybrid (per [`gbrain.md`](../gbrain.md)). This
  is *exactly the hybrid option below*, from the system most architecturally convergent
  with Cicada, and it reports **+31.4 P@5 over vector-only RAG** — most of that lift is the
  BM25 half of hybrid search, which LEANN alone does not give you.

The lesson: the systems Cicada admires didn't choose "Postgres *instead of* markdown" —
the good one chose **markdown-canonical + DB-derived**. That is the pattern to copy.

## What this means for Cicada

1. **Decouple the two decisions.** "What is the source of truth?" (markdown+git — already
   correct, it carries provenance/transparency/portability) is independent from "what
   powers retrieval?" (a derived index). Don't let the index choice threaten the markdown
   layer.

2. **LEANN's core trade is mis-fit for Cicada now.** It optimizes storage at the cost of
   query latency. Cicada has trivial storage and — per D3 — a *new requirement for
   interactive, low-latency retrieval* (the ask/dialectic endpoint and live graph
   filtering). The thesis's "97% storage savings" selling point is technically true but
   strategically irrelevant at 1,882 entities, and the latency cost now actively conflicts
   with D3. This is worth stating honestly in the thesis rather than defending LEANN on
   storage grounds.

3. **D3 (both retrieval modes) pushes toward a real index with hybrid search.** Direct file
   traversal stays for the LLM-follows-wikilinks path. The natural-language ask endpoint
   wants hybrid (BM25+vector) ranking + metadata filters — pgvector or sqlite-vec gives
   that cleanly; LEANN gives you vector-only and you hand-build the rest.

4. **Infra burden is the deciding constraint for a single-user macOS thesis app**, and it
   argues against a Postgres daemon specifically — not against the derived-index idea.
   sqlite-vec captures ~all of pgvector's *relevant* benefit (stored vectors, fast lookup,
   SQL metadata filters, hybrid assemblable) with *none* of the daemon burden.

## Recommendation

**Adopt the HYBRID architecture, with sqlite-vec as the default derived index and pgvector
as the documented upgrade path.**

- **Source of truth stays markdown+git.** Non-negotiable — it is where the thesis's
  transparency/provenance/portability contributions live.
- **Replace LEANN with a stored-embedding derived index**, rebuilt from markdown by the
  Sleep cycle (Sleep already commits a versioned snapshot; index rebuild slots into stage
  5 naturally). This kills LEANN's recompute latency, which now conflicts with D3.
- **Default to `sqlite-vec`** for the index: embedded, no daemon, ships in the app bundle,
  fast enough at Cicada's scale, supports SQL metadata filters. It is the right infra
  profile for a single-user desktop app and keeps onboarding to "drag-to-Applications."
- **Document pgvector as the upgrade path** if/when Cicada wants Honcho-grade hybrid
  (`pg_textsearch` true-BM25 + RRF in one query) or a server deployment. Because the index
  is *derived from markdown*, switching sqlite-vec → pgvector later is a rebuild script, not
  a migration — D1 stays reversible. This is the safest call for a thesis system you may
  defend on multiple axes.

**Net:** keep what makes Cicada special (markdown+git), drop what doesn't fit (LEANN's
storage-for-latency trade), and adopt the pattern gbrain already proved (markdown-canonical
+ DB-derived hybrid retrieval).

*(Confidence: high on "markdown stays canonical" and "derived index beats LEANN for D3";
medium on "sqlite-vec over pgvector" — that hinges on hybrid-search ambition and whether you
ever want Honcho-style true BM25, which sqlite-vec makes you assemble by hand.)*

## Open questions (need Rodrigo's input)

1. **sqlite-vec vs pgvector for the derived index** — the one genuinely open call. How
   important is best-in-class hybrid search (true BM25 via `pg_textsearch` + RRF) to the
   ask/dialectic endpoint's quality story in the thesis? If it's central, pgvector earns
   its daemon; if "good enough hybrid" suffices, sqlite-vec's infra win dominates.
2. **Is the LEANN citation load-bearing in the thesis narrative?** The "Berkeley, 97%
   storage savings, on-device" story is rhetorically clean. Dropping LEANN means rewriting
   that section to be honest that storage was never the binding constraint — query power
   and infra were. Acceptable, but it's a writing/framing decision, not just engineering.
3. **Actual current numbers** — unverified here: run `du -sh memory/leann`, count episode
   chunks, and time a real LEANN query on your Mac. If LEANN latency is already <300ms in
   practice for your corpus, the urgency of replacing it drops (though the hybrid-search and
   metadata-filter arguments for a stored index still stand).
4. **Does D4 (peers/multi-bank) change this?** If multi-bank ever means multiple users or
   shared/queryable banks, the calculus tilts toward pgvector (concurrency, server). For a
   single-user thesis it does not — but worth flagging before committing to sqlite-vec.
5. **Embedding-recompute coupling:** if you ever change the embedding model, a stored index
   needs a re-embed pass; LEANN would also need a full rebuild. Neither is free, but with
   markdown-canonical the re-embed is a deterministic batch job — confirm the Sleep cycle
   owns it.
