# Search everywhere, the server half (Track S-back, G136) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The owner asked for "quick retrieval fast search bars" (Rodrigo 2026-09-23). This track builds
the server half. `GET /search` stops blocking the event loop, honours `kinds` (entities, beliefs,
conversations, sources and papers, inbox), reports honest per-kind `totals`, and returns spans a viewer
can highlight. A derived SQLite FTS5 index — beside the vector index, disposable, never tracked in a
bank's git — makes type-as-you-go (`mode=prefix`) a ~12 ms p95 lookup at the live bank's scale, and
makes names, aliases, claims (history included), conversation passages, paper metadata and inbox
questions findable by the words in them. `mode=hybrid` fuses that lexical leg with the stored vectors
by reciprocal rank. `/conversations/recent?q=` filters titles across the whole bank before its cap. The
palette UI (design §6 S3–S6) is a later track; this plan fixes the wire it builds against.

**Architecture:** Three new services, each owning one thing. `text_fold` is the one folding rule (NFD,
combining marks dropped, lower — the app's QuickMatch normalisation) shared by every server matcher.
`search_index` owns the FTS5 file: schema, full build, request-time incremental refresh from
`bank_index` stamps, one background worker per bank, and a read-only `Reader`; it never ranks.
`search_service` owns retrieval: kinds, QuickMatch-mirrored ranking, RRF fusion with
`SqliteVecIndexer.search_kinds` (one embed), spans, snippets, the `bank_index` fallback, and two
MCP-shaped legs for later adoption. The router is a threadpool call. Sleep rebuilds the file beside
the vectors; the lifespan and a bank switch warm it in the background.

**Tech Stack:** Python 3.12 / FastAPI / Pydantic, SQLite 3.47 FTS5 (`unicode61 remove_diacritics 2`,
prefix indexes) and sqlite-vec, markdown + git bank. No Swift.

**Spec:** `docs/superpowers/specs/2026-09-23-round3-meadow-reach-provenance-design.md` decision 7
(binding), and `docs/superpowers/specs/2026-09-23-round3-design-settings-search-provenance.md` §1.2
(QuickMatch), §3.2 (two tiers and their budgets), §3.3 (groups), §3.9 (the server contract Track S
owns), §3.10 (tests), §6 slices S1–S2. The research both rest on lives in the session scratchpad, not
the repo, and is cited by id exactly as the design doc cites it: R3 §4 P1/P2/P4, R6 §4.2, R8 §3.5.
Backlog: **G136** (filed by Task 6), cross-referencing **G93** (search/ask) and **G123** (graph node
search). Standing rulings: TODO ruling 3 (a `.db` may exist only if deleting it costs CPU and never a
fact; no derived artifact is ever tracked in a bank's git), the telemetry rail (the query is never
logged), ETag ship-together, privacy in docs, portability, Sleep-safety (read paths are engine-free).

---

## What the code actually does today (verified against `feat/search-everywhere` @ `bef2e55`)

**`GET /search`** — `api/routers/search.py` (121 lines):
- `:110-121` — `async def search(q, top_k=8, indexes="entities", …)` calls `_vector_search`
  **synchronously inside `async def`**: it builds a `SqliteVecIndexer`, embeds the query and runs a KNN
  on the event loop (R6 §4.2). `/ask` already moved its work off the loop with `run_in_threadpool`.
- `indexes` is accepted and **never read**; only entities are searched, though the vector index also
  holds `episodes` and `claims`.
- `:81-107` — `_substring_search`, the fallback when vectors return nothing, globs `entities/*.md` and
  runs `markdown_parser.parse` on **every file per request**, matching the **whole query** as one
  substring of name / tags / body. It never reads `aliases` (R3 P1). `:27-41` `_hit_from_file`
  re-parses each vector hit's page too.
- `api/models/schemas.py:796-807` — `SearchHit(id, name, type, status, confidence, score, snippet)`,
  `SearchResponse(results)`: no kind, no offsets, no spans, no totals.
- Swift: `Services/APIClient.swift:1875` `search(q:topK:)` sends `indexes=entities` and **has no
  caller**; `Models/GraphFilter.swift:76-110` `GraphSearchHit` decodes `type`/`status` tolerantly and
  ignores unknown keys, so additive fields are safe for any old client.
- No test exercises `/search` (`grep -rn '"/search' api/tests` finds none).

**The vector index** — `api/services/vector_index.py`:
- `:35`, `:126` — `vector_index.db` lives at `<memory_path>/vector_index.db`, `memory_path` being
  whatever the caller passes (the routers pass `settings.memory_path`, the active-bank resolver,
  `bank_registry.py:89-116`).
- `:272-301` — `_knn` embeds the query on every call, so three kinds cost three embeds.
- `:537-596` — `index_claims` skips every claim with `valid_to` (`:559-560`): superseded claims are
  unsearchable anywhere (R3 P4).
- `:643-664` — `_chunk_episode_body` chunks the **stripped** body into 4,000-char passages with no
  offsets.
- Rebuilt only by Sleep (`sleep_cycle.py:1211-1251`, synchronous inside `async def _run_stages`) and by
  `claim_seeder`. There is no incremental writer seam to follow.

**Derived artifacts and git** — `api/services/bank_registry.py`:
- `:67-80` — `DERIVED_ARTIFACTS = ("vector_index.db", "-wal", "-shm")` feeds `_BANK_GITIGNORE` and
  `duplicate_bank`'s copy exclusion (`:350-358`).
- `:210-220` — `scaffold_bank` writes `.gitignore` for a new bank and, for an existing one, appends
  **only when `vector_index.db` is missing**: a new derived name never reaches an existing bank's
  `.gitignore`. `git_service.commit_changes` stages with `git add -A` (G99a), so an unignored file in a
  bank is committed by the next writer.
- `api/services/sync_service.py:137-194` — the version components stat named files and directories
  (`entities/`, `graph_edges.yaml`, `feeds.yaml`, …), never the bank directory itself or any `*.db`,
  so a new root-level `.db` never moves `/sync/version` (a search can never make the app refetch).
- uvicorn's access log is ON: neither launch path passes `--no-access-log` (the launchd plist,
  `install.sh:343-350`, and the app's spawn, `BackendProcess.swift:68-72`). It writes every request
  line **with its query string** to stdout, which the plist sends to `<repo>/logs/backend.out.log`
  (`install.sh:361`). A `GET /search?q=` per keystroke would put the person's words in that file
  (G136 R22).

**Reusable pieces:**
- `api/services/bank_index.py:62-116` `files(memory_path, subdir)` — the `(mtime_ns, size)`-keyed
  frontmatter cache, one `scandir` per directory; `parse_count` (`:19`) counts real parses.
- `api/services/evidence.py:68` `body_hash`, `:94-105` `source_text` (an episode's evidence text is
  its parsed body, unstripped), `:166-186` `speaker_kind(text, start)`.
- `api/services/claims.py:59` `EVIDENCE_KINDS`, `:113` `Claim` (`valid_to`, `superseded_by`,
  `evidence`), `:246` `parse_claims` (non-strict degrades to `[]`), `:358` `strip_claims_block`.
- `api/services/graph_builder.py:18-34` `summarize` — the `GraphNode.summary` the app's local tier
  will match against.
- `api/services/inbox_service.py:200-230` `_subject_gone`, `:233-285` `load_inbox`;
  `api/services/inbox_questions.py:89-99` `is_deferred`, `:327-342` `decay_question` (decay is served
  as "Still tracking {name}?", never written).
- `mcp/server.py:905-922` `_rrf_fuse` (k = 60, first-seen hit kept), fused at `:953-956`;
  `:1580-1608` `_keyword_search_entities` (whole-query substring, no aliases). **Not edited here.**
- `api/services/providers.py:47` `_EMBED_CACHE` — what "prefix mode never loads the model" is
  asserted against (design §3.10).
- `api/routers/conversations.py:90-133` — `/conversations/recent` filters `harness`/`origin` before
  the cap and folds both into the ETag `extra`; `api/services/session_stats.py:197-228`
  `aggregate_conversations` projects every group (one `transcript_exists` probe each) before any
  filter runs.
- `api/routers/sources.py:478` imports `link_enrichment._extract_description_section` — the precedent
  for calling another module's private helper when the point is to share ONE rule.

**Measured while planning (2026-09-23; synthetic banks in the session scratchpad — nothing read from a
real bank):**
- 2,000 entities (3 claims each) + 1,500 episodes (10.8 MB of turns): a warm `bank_index` scan of both
  directories is **5.6 ms p50**, a cold one 0.49 s.
- One shared FTS5 table with a `kind` column: prefix-query p95 **142 ms** (every match of every kind is
  ranked before the filter). Per-kind tables: **52 ms** p95, dominated at 2–3 character prefixes by
  `ORDER BY bm25` over passages (33 ms) and `count(DISTINCT ref)` (33 ms).
- Encoding the episode in the rowid (`doc_id << 16 | n`): distinct-episode count **2.3 ms**,
  newest-first passages **0.4 ms**, at a two-letter prefix.
- Prefix indexes `2 3` → `2 3 4`: 4-character p95 22 → 16 ms; file 37 → 43 MB.
- This plan's code, prototyped and run through Task 5's own test at the same scale with pages up to
  8,000 characters: full build **5.5 s**; `mode=prefix` **p50 5.9 ms / p95 12.1 ms**; with a staleness
  scan on every request **p95 21.8 ms**; `mode=hybrid` with a fake embedder **p50 14.6 ms / p95
  36.3 ms**. The full suite went 2225 → **2284 passed**.
- The plan critic applied every task to a scratch copy of `bef2e55`, confirmed the 2284, then added
  five fixes (R2's worktree/submodule case, dropped pages never indexed, R10 in hybrid, the
  access-log redaction R22, a tolerant number in the fallback). Each came with a test that fails
  without the fix, and the suite went to **2287 passed**. The budgets still held on that run: build
  5.6 s, prefix p95 11.7 ms (22.0 ms with a scan per request), hybrid p95 40.5 ms.

**Baseline on this base:** backend **2225 passed** (TODO.md, 2026-09-06 — re-measure before Task 1).

---

## Global Constraints

- Work ONLY in `<worktree>` — the `.worktrees/s` checkout the orchestrator's brief names (branch
  `feat/search-everywhere`, based on `dev` @ `bef2e55`). Every shell command is
  `cd <worktree> && <cmd>` with the ABSOLUTE path from the brief (zoxide hijacks a relative `cd`;
  ignore its stderr warning). Never an unquoted `--include=*.ext` (zsh globs it).
- NEVER read `<repo>/memory` (any bank), `~/.cicada`, `~/Library` or `~/.claude/projects`. Fixtures
  are synthetic: `alpha-project`, `bob-example`, `example.com`, made-up syllable words.
- Python: `cd <worktree> && api/.venv/bin/python -m pytest <files> -q -p no:cacheprovider`; the full
  `api/tests` suite must report **0 failures**.
  `test_agent_provenance.py::test_a_decay_only_change_lands_in_its_own_cicada_authored_commit` is
  order-dependent and pre-existing — if it is the ONLY red, re-run it alone and report both results.
- **Do not edit `mcp/server.py`** (Track R is moving its tool bodies). No Swift, nothing under `app/`.
- Never `git add -A`; stage the named files only. Never commit `memory/`, `logs/`, `.claude/`,
  `api/.venv` or `*-report.md`. No push, no new branches or worktrees, no subagents. Ignore Devin/PR
  comments.
- **The query is never logged, stored or sent to telemetry** (K9). No `logger` call in the new code
  interpolates `q`, a token, a snippet or a hit's text. A failure on the search path
  (`search_service`, and the embed inside `vector_index.search_kinds`) logs `type(exc).__name__`
  only, because an embedding provider's error can echo its input. The index's maintenance logs may
  carry an exception message: it names a file or a table, and the index never sees the query.
  uvicorn's access log is redacted for the two query-bearing paths (G136 R22). Task 3's
  `test_the_query_is_never_logged` and `test_the_access_log_never_carries_the_query` pin both.
- **No LLM anywhere in search.** `mode=prefix` never constructs a `SqliteVecIndexer` and never touches
  `providers._EMBED_CACHE`.
- `search_index.db` (+ `-wal`/`-shm`) lives in the bank directory beside `vector_index.db` and is
  excluded from git **before** it is first created (G136 R2).
- Privacy (standing, 2026-09-02): no owner name, no author-machine absolute path, no bank contents in
  code, docs, commits or PR bodies — write `<worktree>` / `<repo>`.
- Docstrings explain **why**, citing the G-row, the ruling (`G136 R<n>`) or the research id behind a
  rule, at the density of the files touched. The ids `R-S<n>` already belong to round 2's Sources v2;
  this track's rulings are `G136 R<n>`.
- The code blocks below were prototyped and run against the full suite before this plan was written,
  and run again by the plan critic, fixes included (2287 passed). Copy them exactly. Line numbers are
  from `bef2e55` and drift as tasks land, so read the cited code before editing it.

---

## Rulings (binding)

Where the brief left a choice, this plan decides it. Each ruling carries its reason; no task re-opens
one.

- **G136 R1 — One FTS5 file per bank, where the vector index lives, never inside it.**
  `<bank>/search_index.db`, from the `memory_path` the caller passes (the router passes
  `settings.memory_path`, the active-bank resolver; MCP will pass its own resolved path). The index
  module never resolves a bank itself (the split-brain rule). A separate file rather than tables inside
  `vector_index.db`: deleting one must never delete the other (vectors cost minutes of embedding, this
  file seconds of CPU), and the per-request incremental writes here must never queue behind Sleep's
  vector-rebuild transaction on one file lock.
- **G136 R2 — Never tracked: `.git/info/exclude`, written before the file exists.**
  `bank_registry.DERIVED_ARTIFACTS` gains the three `search_index.db*` names (so a *new* bank's
  `.gitignore` and `duplicate_bank`'s exclusion cover them), and a new `ensure_derived_excluded(path)`
  appends any missing name to `.git/info/exclude`; `scaffold_bank` calls it, and the index calls it
  before its first build. Not `.gitignore` for existing banks: `scaffold_bank`'s append branch keys on
  `vector_index.db` alone, and editing a tracked `.gitignore` dirties the tree — the next `git add -A`
  writer sweeps it into its own commit under the wrong author (the G85 smear) and it can trip the Sleep
  tail's clean-tree guard. `exclude` is never tracked and never dirties anything. A bank checked out
  as a git **worktree or submodule** has a `.git` *file* (`gitdir: …`); `_git_dir` follows it (and a
  worktree's `commondir`) to the directory git really reads `info/exclude` from. Without that,
  exactly those banks would get an unprotected 40 MB file on the next `git add -A` (portability).
- **G136 R3 — Freshness is a request-time staleness check plus Sleep's full rebuild, not a hook per
  writer.** The vector index has no incremental writer seam to follow, and Cicada has a dozen
  page/episode writers (MCP save, the Stop hook, imports, Telegram, connectors, bookmarks, notes,
  feeds, inbox resolve, agent claims, link enrichment, the demo bank): a hook in each is invasive, and
  one missed writer is a silently stale index. `ensure_fresh` compares `bank_index`'s `(mtime_ns, size)`
  stamps (the mechanism `/status` already relies on; ~6 ms warm at 3,500 files) with the stamps the
  index recorded, re-indexes what moved **inline when ≤ 64 files changed**, hands a bigger burst to one
  background worker (answering `stale` and serving the current index meanwhile), and throttles itself to
  one check per second (`STALENESS_TTL_S`). Sleep rebuilds the whole file beside the vectors (the
  self-healing pass, off the event loop); the lifespan and `POST /banks/{name}/activate` warm it in the
  background.
- **G136 R4 — Six per-kind FTS5 tables, `unicode61 remove_diacritics 2`, prefix `2 3 4`.** `ent`
  (entity pages except media), `med` (media pages, with paper authors / arXiv id / DOI / site), `clm`
  (every claim, superseded included), `epi` (episode titles), `pas` (episode passages), `inb` (inbox
  questions), plus the plain tables `docs`, `claim_ref`, `claim_evidence` and `meta`. Per-kind tables
  because a shared table ranks every match of every kind before filtering (measured p95 142 ms against
  52 ms). Passages are 600 characters that **tile the body exactly** (no overlap, no gap), with offsets
  into the evidence text.
- **G136 R5 — `rowid = doc_id << 16 | n`.** A document's rows are one range (delete is a range scan), a
  passage names its episode without a column read (distinct-episode count 2.3 ms instead of 33 ms), and
  a re-indexed document gets a fresh, larger `doc_id`, so `ORDER BY rowid DESC` means "most recently
  written first".
- **G136 R6 — Prefix mode orders conversation passages newest-written first and never computes bm25
  for them** (0.4 ms instead of 33 ms at two letters); hybrid mode ranks them by bm25. Title matches rank
  before passage matches in both.
- **G136 R7 — In-kind ranking mirrors QuickMatch tiers 0–2 with QuickMatch's weights; tiers 3–4 stay
  local.** Whole field = 0, field prefix = 1, word-start prefix = 2; name 1.0, alias 0.9, keyword/tag
  0.7, body 0.4; score = Σ (5 − tier) × weight (design §1.2). Initials and mid-word substrings have no
  index behind them server-side (a trigram tokenizer would roughly triple the file and still not give
  initials); the app's local tier covers them. The formula stays identical even where it surprises (an
  exact alias outranks a name prefix), so the two tiers never disagree about one name. Archived pages
  rank after every live page (the `search_entities` fallback tier). `dropped` pages (user-dismissed,
  never resurfaced) are **never indexed**: their `docs` row keeps the file's stamp, but they get no
  FTS row and no claims. So they are never returned and never inflate a total (R11), and a vector hit
  on one is filtered out when it is hydrated.
- **G136 R8 — `kinds` = `entity | claim | episode | media | inbox`.** The brief adds `inbox` to §3.9's
  four. Plural and palette names are accepted (`conversations`, `beliefs`, `sources`, `papers`, …).
  The legacy `indexes` parameter is honoured only when `kinds` is absent; nothing recognised means
  entities only (today's behaviour). A media page is reported once: under `media` when `media` was asked
  for, otherwise under `entity` — so the old call shape still returns every page.
- **G136 R9 — The claim leg into the entity group is lexical in both modes.** R3 P2 wants claims as a
  third recall leg mapped to their subject. A *vector* claim leg always returns k neighbours, so it
  hands every page with nearby claims a second, always-present semantic vote on top of the entity
  vectors (in a one-claim fixture it put that claim's subject above the only true semantic match).
  Current claims whose words match are mapped to their page; vector claims still rank the `claim` group
  itself. In prefix mode claim-reached pages come after the lexical ones (the exact-name hit stays on
  top); in hybrid they are the third RRF list.
- **G136 R10 — Superseded claims are indexed and shown as history, never as the present.** They carry
  `validTo`/`supersededBy`, rank after every current claim **in both modes**, and never lead to their
  subject. In hybrid that takes a stable sort before the cut: the vector claims index holds only
  current claims, so a superseded claim can only arrive lexically, and RRF alone would tie it with the
  first semantic neighbour. The vector claims index stays current-only; R3 P4(a)'s dead
  `include_superseded` is not this track.
- **G136 R11 — `totals` are exact lexical counts.** The documents of a kind that contain every query
  token as a word-start prefix — the one countable set, so "Show all N" is never a guess.
  Semantic-only neighbours are ranked, flagged `matchedField: "semantic"`, and never counted. The inbox
  total is omitted when more than 200 matches would need filtering. `mode` echoes what ran (`lexical`
  when hybrid was asked for and no vector index answered); `indexState` is
  `ready | stale | building | unavailable`.
- **G136 R12 — While the index is building or unavailable, `/search` still answers:** entity and media
  pages from `bank_index`'s frontmatter cache (name, aliases, tags — never a body read, never a parse
  per request), fused with the vector entity leg in hybrid; claims, conversations and inbox come back
  empty and `indexState` says why. A broken file is logged by exception class and falls back. Never a
  500.
- **G136 R13 — Spans are exact or absent.** A passage hit's span is the **line** of the best passage
  that holds the first match — tighter than the passage, and `text[start:end]` still contains the match
  (design §3.10) — with the evidence text's `hash` and an `evidenceKind` from `evidence.speaker_kind`. A
  title-only match carries no span. A semantic-only conversation is located by `str.find` of its vector
  chunk in the concatenated passages (they tile the body) — never fuzzy (G118 R5) — and carries no span
  when not found. Claim hits carry their first stored evidence span.
- **G136 R14 — RRF is ported, not imported.** The API never imports the MCP server (`mcp` imports
  `api.services`, never the reverse). `search_service.rrf_fuse` is the same formula (k = 60, first-seen
  hit, stable order), pinned by a parity test against `mcp._rrf_fuse`, so Track R can make the MCP copy
  an import of this one.
- **G136 R15 — One embed per hybrid request.** `SqliteVecIndexer.search_kinds(query, {kind: k})`
  embeds once and runs each KNN with that vector (`_knn` gains an optional `qvec`); the existing
  `search_*` methods are unchanged.
- **G136 R16 — The inbox group is filtered exactly as `GET /inbox` filters it:** deferred items
  (`inbox_questions.is_deferred`) and items whose subject is gone (`inbox_service._subject_gone` — a
  deliberate private call, precedent `sources.py:478`) are not served; a decay item is indexed under
  the words it is served as (`decay_question`).
- **G136 R17 — `/conversations/recent?q=`** is a folded-substring AND over titles
  (`text_fold.contains_all`), applied to the raw groups **before** projection and the cap (a
  filtered-out row never costs its transcript probe), and folded into the ETag `extra` **only when
  present**, so every existing client's validator stays byte-identical. The CAPPED rule in CLAUDE.md
  stays true: the list is still never a membership test.
- **G136 R18 — The latency budget is measured on the server twin:** `search_service.search`, which the
  router runs in its threadpool, over a synthetic 2,000-entity / 1,500-episode bank generated from a
  fixed seed and made-up syllables (no dictionary file, the same bank on every machine). Asserted:
  prefix p95 ≤ 50 ms with the default freshness TTL **and** with a staleness scan on every request;
  hybrid p95 ≤ 200 ms with a fake embedder (fusion and hydration, not a model). Numbers print with `-s`.
- **G136 R19 — No ETag on `/search`.** A per-keystroke query is never a Store domain (K10); there is
  nothing to map in `VersionVector`.
- **G136 R20 — The citations read ships now; the endpoint does not.** §3.9 item 3's claims table carries
  `(evidence_episode, start, end, kind, hash)` and §4.8 item 3 says the same table answers
  `GET /episodes/{id}/citations`: `claim_evidence` stores every span of every claim, and
  `Reader.claims_citing(episode_id)` returns them. The endpoint is Track P's P4.
- **G136 R21 — One folding rule, `text_fold`:** NFD, combining marks dropped, `lower` —
  QuickMatch's normalisation and the query-side twin of `remove_diacritics 2`. *(Amended at the final
  review: the first cut used NFKD + `casefold`, which rewrote "ß" to "ss" and the "ﬁ" ligature and
  full-width letters to ASCII while `unicode61` indexes them as written, so the exact stored spelling
  missed the index and only the fallback found it. The Task 1 code below is the historical first cut.)* Offsets are code points
  (Unicode scalars, the app's `ScalarSlice` unit). ASCII takes a `lower()` fast path with an identity
  map (an 8,000-character page fell from ~2 ms to 0.16 ms per highlight).
- **G136 R22 — The query never reaches a log, uvicorn's access log included.** Design §3.8 says the
  query is never logged or stored anywhere except the `GET /search` request itself. uvicorn logs that
  request line, query string included, to `<repo>/logs/backend.out.log` under launchd. `api/main.py`
  attaches a `logging.Filter` to `uvicorn.access` that replaces the query string of `/search` and
  `/conversations/recent` with `…` and leaves every other line alone. The filter is used instead of
  `--no-access-log` because `install.sh` never rewrites a plist behind a running backend, and the
  app's spawn is Swift: a flag would miss existing installs, and a filter holds whatever flags uvicorn
  was started with. uvicorn configures its loggers before it imports the app, so the filter is never
  replaced.

---

## The wire (what the palette track builds against)

`GET /search`

| Param | Values | Default | Notes |
|---|---|---|---|
| `q` | ≤ 200 chars | required | Tokens shorter than 2 characters are ignored; none left → no rows (prefix) or semantic rows only (hybrid). |
| `kinds` | csv of `entity, claim, episode, media, inbox` (also `entities, claims, beliefs, episodes, conversations, sources, papers`) | `entity` | Results come grouped in that fixed order. |
| `mode` | `prefix` \| `hybrid` | `hybrid` | `prefix` never embeds. Anything else → 422. |
| `per_kind` | 1–20 | `min(top_k, 20)` | Above 20 → 422. |
| `top_k`, `indexes` | legacy | `8`, none | The pre-G136 call shape stays valid. |

Response (camelCase): `{results: [SearchHit], totals: {kind: int}, mode: "prefix"|"hybrid"|"lexical",
indexState: "ready"|"stale"|"building"|"unavailable"}`.

`SearchHit` = the old seven (`id, name, type, status, confidence, score, snippet`) plus `kind, subtitle,
snippetOffsets, matchedField, subjectId, episodeId, conversationId, harness, origin, timestamp, start,
end, hash, evidenceKind, validFrom, validTo, supersededBy` (all optional). Per kind:

| kind | `id` | `name` | `type` | spans | also |
|---|---|---|---|---|---|
| entity | entity id | page name | page type | — | `subtitle` = the alias that matched, or the claim text when `matchedField: claim` |
| media | entity id | title | `media` | — | `subtitle` = authors ("A, B, C et al.") or site; `origin`; `timestamp` = saved date |
| claim | claim id | claim text | subject's type | `episodeId/start/end/hash/evidenceKind` of its first evidence span | `subjectId`; `subtitle` = subject name; `validTo`/`supersededBy` = history |
| episode | episode (evidence doc) id | title | `episode` | the matching line, `hash` of the evidence text | `conversationId`, `harness`, `origin`, `timestamp` |
| inbox | inbox item id | the served question | the item's kind | — | `subjectId` = entity id; `subtitle` = entity name |

`matchedField` ∈ `name | alias | keyword | body | claim | semantic`. `snippetOffsets` are
`[start, end]` code-point ranges into `snippet`. `score` orders rows inside one response only.

The `episode` group has one row per episode (evidence document), and `totals.episode` counts episodes.
Design §3.3 shows conversations "grouped by conversation id"; the palette does that grouping on
`conversationId`, because one conversation can span several episodes (an imported thread, a resumed
session). `dropped` pages never appear in any group or total (R7).

`GET /conversations/recent?q=` — a title filter before the cap (G136 R17).

---

## File map

| File | Responsibility |
|---|---|
| `api/services/text_fold.py` (new) | `fold`, `fold_with_map`, `query_tokens`, `words`, `contains_all`, `match_offsets` — the one folding rule (R21) |
| `api/services/session_stats.py` | `aggregate_conversations(q=)` — the title filter before projection and cap |
| `api/routers/conversations.py` | `/conversations/recent?q=`; ETag `extra` appended only when present |
| `api/services/bank_registry.py` | `DERIVED_ARTIFACTS` += `search_index.db*`; `_git_dir` (follows a worktree/submodule `.git` file); `ensure_derived_excluded`; `scaffold_bank` calls it (R2) |
| `api/services/search_index.py` (new) | the FTS5 file: schema, build, incremental refresh, freshness, background worker, `Reader` (R1, R3–R6, R20) |
| `api/services/vector_index.py` | `_knn(…, qvec=)`, `search_kinds` — one embed for several kinds (R15) |
| `api/models/schemas.py` | `SearchHit` additive fields; `SearchResponse.totals/mode/index_state` |
| `api/services/search_service.py` (new) | kinds, ranking, fusion, spans, snippets, fallback, MCP-shaped legs (R7–R14, R16) |
| `api/routers/search.py` | rewritten: parameters + `run_in_threadpool` |
| `api/services/sleep_cycle.py` | rebuild the file beside the vectors, off the loop; a failure is a warning |
| `api/main.py` | Task 3: the `uvicorn.access` filter that redacts the query string (R22). Task 4: warm the index at launch |
| `api/routers/banks.py` | warm the index in the background on a bank switch |
| Tests (new) | `test_text_fold.py`, `test_search_index.py`, `test_search_service.py`, `test_sleep_search_index.py`, `test_search_latency.py` |
| Tests (appended) | `test_session_stats.py` |
| Docs | `docs/goals/memory-evolution.md` (G136), `CLAUDE.md` (Storage Layer, API traps, Key Design Decisions), `docs/goals/TODO.md` |

Expected backend counts after each task: **2235 → 2256 → 2280 → 2284 → 2287** passed (+10, +21, +24,
+4, +3 on 2225). If the base count differs, the deltas are what must hold.

---

### Task 1: One folding rule, and `/conversations/recent?q=` before the cap (S1, R17, R21)

The smallest server change the palette needs, and the folding rule every later matcher shares. The
branch stays shippable: one additive query parameter; no existing ETag changes.

**Files:**
- Create: `api/services/text_fold.py`
- Modify: `api/services/session_stats.py:26` (import), `:197-228` (`aggregate_conversations`)
- Modify: `api/routers/conversations.py:90-133` (`recent_conversations`)
- Test: `api/tests/test_text_fold.py` (new); append to `api/tests/test_session_stats.py`

**Interfaces:**
- Produces `text_fold.fold`, `fold_with_map`, `query_tokens`, `words`, `contains_all`,
  `match_offsets`, `MIN_TOKEN_CHARS`, `MAX_TOKENS`; `session_stats.aggregate_conversations(…, q=None)`;
  `GET /conversations/recent?q=`.
- Consumes `unicodedata`, `session_stats._group`, `sync_service.etag_for`.

- [ ] **Step 1: Failing tests.** Create `api/tests/test_text_fold.py`:

````python
"""G136 — the one folding rule every server-side matcher shares (pure)."""
from __future__ import annotations

from api.services import text_fold


def test_fold_drops_case_and_diacritics_like_quickmatch():
    assert text_fold.fold("Zürich CAFÉ") == "zurich cafe"
    # A decomposed accent (u + U+0308) folds the same as the precomposed one.
    assert text_fold.fold("Zu\u0308rich") == "zurich"


def test_query_tokens_split_like_unicode61_and_drop_one_letter_tokens():
    assert text_fold.query_tokens("  Zürich, a CAFÉ café x_y") == ["zurich", "cafe"]
    assert text_fold.query_tokens("a b") == []
    assert text_fold.query_tokens("") == []
    assert len(text_fold.query_tokens(" ".join(f"w{i}" for i in range(20)))) == text_fold.MAX_TOKENS


def test_words_are_the_folded_index_tokens():
    assert text_fold.words("Zürich-Office, HQ_2") == ["zurich", "office", "hq", "2"]


def test_contains_all_is_substring_and_across_words():
    assert text_fold.contains_all("Planning alpha-project", "alpha plan")
    assert not text_fold.contains_all("Planning alpha-project", "alpha beta")
    assert text_fold.contains_all("anything", "   ")


def test_match_offsets_are_word_start_prefixes_in_original_code_points():
    assert text_fold.match_offsets("Zürich café", ["zur", "caf"]) == [[0, 3], [7, 10]]
    # The decomposed accent sits inside the span: 4 code points for "Zür".
    assert text_fold.match_offsets("Zu\u0308rich", ["zur"]) == [[0, 4]]
    # Word-start only: "cap" inside "escape" is not a hit.
    assert text_fold.match_offsets("capital escape cap", ["cap"]) == [[0, 3], [15, 18]]
    assert text_fold.match_offsets("alpha", []) == []


def test_match_offsets_slice_back_to_the_matched_text():
    text = "We moved the index to sqlite-vec so search is fast"
    spans = text_fold.match_offsets(text, text_fold.query_tokens("sqlite vec"))
    assert [text[s:e] for s, e in spans] == ["sqlite", "vec"]
````

Append to the end of `api/tests/test_session_stats.py` (it already defines `_episode`, `_client`,
`_never`, `UUID_A`, `UUID_B` and imports `bank_index`, `session_stats`):

````python
# --- G136: ?q= title filter, applied before the cap ---------------------------


def test_aggregate_conversations_q_filters_titles_before_the_cap(tmp_path):
    """The newest conversation overall is NOT the newest match: a filter
    applied after the cap would return nothing for ``limit=1``."""
    memory = tmp_path / "memory"
    _episode(memory, "ep_2026-08-01_001", timestamp="2026-08-01T09:00:00Z",
             session_id=UUID_A, title="Planning alpha-project")
    _episode(memory, "ep_2026-08-02_001", timestamp="2026-08-02T09:00:00Z",
             session_id=UUID_B, title="Shipping beta")
    bank_index.invalidate()
    rows = session_stats.aggregate_conversations(
        memory, limit=1, transcript_exists=_never, q="alpha")
    assert [r["conversation_id"] for r in rows] == [UUID_A]


def test_aggregate_conversations_q_is_case_and_accent_blind_and_ands_words(tmp_path):
    memory = tmp_path / "memory"
    _episode(memory, "ep_2026-08-01_001", timestamp="2026-08-01T09:00:00Z",
             session_id=UUID_A, title="Zürich Planning notes")
    bank_index.invalidate()
    hit = session_stats.aggregate_conversations(memory, transcript_exists=_never, q="zurich PLAN")
    miss = session_stats.aggregate_conversations(memory, transcript_exists=_never, q="zurich beta")
    assert [r["conversation_id"] for r in hit] == [UUID_A]
    assert miss == []


def test_aggregate_conversations_q_skips_the_transcript_probe_for_filtered_rows(tmp_path):
    memory = tmp_path / "memory"
    _episode(memory, "ep_2026-08-01_001", timestamp="2026-08-01T09:00:00Z",
             session_id=UUID_A, title="Planning alpha")
    _episode(memory, "ep_2026-08-02_001", timestamp="2026-08-02T09:00:00Z",
             session_id=UUID_B, title="Shipping beta")
    bank_index.invalidate()
    probed: list[str] = []

    def spy(project_dir, session_id, *, root=None):
        probed.append(session_id)
        return False

    session_stats.aggregate_conversations(memory, transcript_exists=spy, q="alpha")
    assert probed == [UUID_A]


def test_recent_endpoint_q_filter_applies_before_the_cap_and_varies_the_etag(tmp_path, monkeypatch):
    client, memory = _client(tmp_path, monkeypatch)
    _episode(memory, "ep_1", timestamp="2026-08-01T09:00:00Z", session_id=UUID_A,
             title="Planning alpha")
    _episode(memory, "ep_2", timestamp="2026-08-02T09:00:00Z", session_id=UUID_B,
             title="Shipping beta")
    bank_index.invalidate()

    filtered = client.get("/conversations/recent", params={"limit": 1, "q": "alpha"})
    assert [r["conversationId"] for r in filtered.json()] == [UUID_A]
    unfiltered = client.get("/conversations/recent", params={"limit": 1})
    assert [r["conversationId"] for r in unfiltered.json()] == [UUID_B]
    assert filtered.headers["ETag"] != unfiltered.headers["ETag"]
    # Whitespace is no filter, and adds nothing to the ETag recipe — an
    # existing client's validator is byte-identical to before G136.
    blank = client.get("/conversations/recent", params={"limit": 1, "q": "   "})
    assert blank.headers["ETag"] == unfiltered.headers["ETag"]
````

- [ ] **Step 2: Run, expect FAIL.**
  `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_text_fold.py api/tests/test_session_stats.py -q -p no:cacheprovider`
  → `ERROR collecting api/tests/test_text_fold.py` (`ImportError: cannot import name 'text_fold'`) and
  pytest stops. Run `api/tests/test_session_stats.py` alone to see the four new tests fail: three with
  `TypeError: aggregate_conversations() got an unexpected keyword argument 'q'`, and the endpoint test
  because `?q=` is ignored (the newest conversation comes back, not the match).

- [ ] **Step 3: Implement.** Create `api/services/text_fold.py`:

````python
"""One folding rule for every server-side text match (G136).

The app's ``QuickMatch`` (round-3 design §1.2) folds both sides with
``.caseInsensitive`` + ``.diacriticInsensitive`` so "Zurich" finds "Zürich".
The server has three matchers that must agree with it and with each other —
the FTS5 index (``unicode61 remove_diacritics 2`` folds the indexed side),
the query tokens that drive it, and the ``/conversations/recent?q=`` title
filter — so the query side is folded here, once, the same way: NFKD, drop
combining marks, ``casefold``.

``match_offsets`` returns spans in **code points** (Python ``str`` indices),
which are Unicode scalars — the unit the app's ``ScalarSlice`` slices by
(design §4.10), so a bold range lands on the same characters on both sides.
Pure and engine-free: nothing here reads a file.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

# FTS5's unicode61 treats letters, numbers and private-use code points as
# token characters and everything else (including "_") as a separator; the
# query tokenizer splits the same way so a query token is always a whole
# index token prefix.
_SEPARATOR_RE = re.compile(r"[\W_]+", re.UNICODE)

# A one-character prefix matches a large share of the index and has no
# prefix index behind it; the palette never sends one (design §3.2: queries
# under 2 characters make no request), and the server does not search on one.
MIN_TOKEN_CHARS = 2
MAX_TOKENS = 8


def fold(text: str | None) -> str:
    """NFKD, combining marks dropped, ``casefold`` — "Zürich" → "zurich"."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


@lru_cache(maxsize=4096)
def _fold_char(ch: str) -> str:
    return fold(ch)


def fold_with_map(text: str) -> tuple[str, "list[int] | range"]:
    """``fold(text)`` plus, for every folded character, the index of the
    source character it came from — so a match found in folded space maps
    back to exact offsets in the original (a decomposed "u" + U+0308 folds to
    one "u" but spans two source code points).

    ASCII — most of a bank — folds to ``lower()`` one-to-one, so the map is
    the identity ``range`` and costs nothing; everything else goes through a
    per-character cache (an 8,000-character page took ~2 ms per call before
    either, measured 2026-09-23, and a result row may fold two of them)."""
    text = text or ""
    if text.isascii():
        return text.lower(), range(len(text))
    out: list[str] = []
    back: list[int] = []
    for i, ch in enumerate(text):
        for c in _fold_char(ch):
            out.append(c)
            back.append(i)
    return "".join(out), back


def query_tokens(q: str | None) -> list[str]:
    """Folded, deduplicated tokens of a query, in order, at most ``MAX_TOKENS``.

    Tokens shorter than ``MIN_TOKEN_CHARS`` are dropped; a query made only of
    them yields ``[]`` (no lexical search), never a one-letter prefix scan.
    """
    seen: set[str] = set()
    out: list[str] = []
    for tok in _SEPARATOR_RE.split(fold(q)):
        if len(tok) < MIN_TOKEN_CHARS or tok in seen:
            continue
        seen.add(tok)
        out.append(tok)
        if len(out) == MAX_TOKENS:
            break
    return out


def words(text: str | None) -> list[str]:
    """The folded index tokens of ``text``, in order (unicode61's split)."""
    return [w for w in _SEPARATOR_RE.split(fold(text)) if w]


def contains_all(text: str | None, q: str | None) -> bool:
    """Every whitespace-separated word of ``q`` is a folded SUBSTRING of
    ``text`` (AND). The title filter's rule: a title is short, so "contains"
    — QuickMatch's loosest tier — is the right strength; an empty ``q``
    matches everything."""
    words = fold(q).split()
    if not words:
        return True
    hay = fold(text)
    return all(w in hay for w in words)


def _is_word_start(folded: str, p: int) -> bool:
    return p == 0 or not folded[p - 1].isalnum()


def match_offsets(text: str | None, tokens: list[str]) -> list[list[int]]:
    """``[[start, end], …]`` of every word-start prefix match of any token in
    ``text``, merged and sorted, in code points of the ORIGINAL text.

    Word-start prefix is exactly what an FTS5 prefix query matched, so a
    highlight never claims a match the index did not make (and never invents
    a substring hit inside a word).
    """
    text = text or ""
    if not text or not tokens:
        return []
    folded, back = fold_with_map(text)
    spans: list[tuple[int, int]] = []
    for tok in tokens:
        start = folded.find(tok)
        while start != -1:
            if _is_word_start(folded, start):
                end = start + len(tok) - 1
                spans.append((back[start], back[end] + 1))
            start = folded.find(tok, start + 1)
    if not spans:
        return []
    spans.sort()
    merged: list[list[int]] = [list(spans[0])]
    for s, e in spans[1:]:
        if s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return merged
````

In `api/services/session_stats.py`, replace the import line

```python
from api.services import bank_index
```

with

```python
from api.services import bank_index, text_fold
```

and in `aggregate_conversations` replace the signature tail, docstring end and first statement

```python
    harness: str | None = None,
    origin: str | None = None,
) -> list[dict]:
```

```python
    limit. ``harness="unknown"`` matches rows whose harness is empty — the
    same value the overview reports for them.
    """
    groups = _group(Path(memory_path))
```

with

```python
    harness: str | None = None,
    origin: str | None = None,
    q: str | None = None,
) -> list[dict]:
```

```python
    limit. ``harness="unknown"`` matches rows whose harness is empty — the
    same value the overview reports for them.

    ``q`` (G136, design §3.7/§3.9 item 4) is a title filter applied BEFORE
    the cap for the same reason: the Harness-conversations field filters the
    ≤ 200 rows it holds locally, and "beyond the cap" must mean the whole
    bank, not the next page. Every word of ``q`` must be a folded substring
    of the title (``text_fold.contains_all`` — case- and accent-blind, the
    app's QuickMatch normalisation). It runs on the raw groups, before
    ``project_conversation``, so a filtered-out row never costs its
    ``transcript_exists`` probe.
    """
    groups = _group(Path(memory_path))
    if q is not None and q.strip():
        groups = {
            cid: g for cid, g in groups.items() if text_fold.contains_all(g["title"], q)
        }
```

In `api/routers/conversations.py` `recent_conversations`: add the parameter after `origin`

```python
    q: str | None = Query(None, max_length=200),
```

append to the docstring, after "Both fold into the ETag: they change the body without moving any
component.",

```python

    ``q`` (G136) is a title filter, also applied BEFORE the cap and folded
    into the ETag the same way; whitespace-only is no filter. The ``|q=``
    part is appended only when a filter is present, so every existing
    client's ETag stays byte-identical. The query is never logged — it is
    the person's words (K9); ``api/main.py`` strips it from uvicorn's
    access log (G136 R22).
```

replace

```python
    etag = sync_service.etag_for(
        settings.memory_path, "episodes", "entities",
        extra=f"limit={limit}|harness={harness or ''}|origin={origin or ''}",
    )
```

with

```python
    q = (q or "").strip() or None
    extra = f"limit={limit}|harness={harness or ''}|origin={origin or ''}"
    if q:
        extra += f"|q={q}"
    etag = sync_service.etag_for(settings.memory_path, "episodes", "entities", extra=extra)
```

and pass `q=q,` after `origin=origin,` in the `run_in_threadpool(session_stats.aggregate_conversations, …)`
call.

- [ ] **Step 4: Run, expect PASS.** Same command as Step 2 → all green (the new 10 included).

- [ ] **Step 5: Full suite.** `cd <worktree> && api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider`
  → 0 failures, **2235 passed** (base + 10).

- [ ] **Step 6: Commit.**

```bash
cd <worktree> && git add api/services/text_fold.py api/services/session_stats.py api/routers/conversations.py api/tests/test_text_fold.py api/tests/test_session_stats.py && git commit -F - <<'EOF'
feat(conversations): ?q= title filter before the cap, and one folding rule (G136)

/conversations/recent?q= filters titles across the whole bank before the
limit, like harness/origin, and folds into the ETag only when present so
existing validators stay byte-identical (G136 R17). text_fold is the one
folding rule every server matcher shares: NFKD, no combining marks,
casefold, offsets in code points (G136 R21).

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 2: The derived FTS5 index, excluded from git before it exists (S2, R1–R6, R20)

The index as a standalone service, fully tested, not yet read by anything. The branch stays shippable:
the only behaviour change outside the new module is that `scaffold_bank` writes `.git/info/exclude`
lines, which touch nothing tracked.

**Files:**
- Modify: `api/services/bank_registry.py:34` (import), `:67-71` (`DERIVED_ARTIFACTS`), new
  `_git_dir` + `ensure_derived_excluded` above the `# --- Resolution` banner (`:82`), `:236-247` (end
  of `scaffold_bank`)
- Create: `api/services/search_index.py`
- Test: `api/tests/test_search_index.py` (new)

**Interfaces:**
- Produces `bank_registry.ensure_derived_excluded(path) -> bool` (and its private `_git_dir`);
  `search_index.DB_FILE`,
  `SCHEMA_VERSION`, `STALENESS_TTL_S`, `INLINE_REFRESH_LIMIT`, `ROW_BITS`, `db_path`, `fts5_available`,
  `match_expression`, `passage_spans`, `ensure_fresh(memory_path, *, wait=False, max_age_s=None) -> str`,
  `rebuild(memory_path) -> int`, `warm_in_background`, `wait_idle`, `reset`, `invalidate`, `Doc`,
  `Reader` (`ranked`, `count`, `count_episodes`, `passages`, `claims`, `claims_by_id`, `claims_citing`,
  `docs`, `docs_by_ref`, `column`, `passage_text`, `episode_passages`).
- Consumes `bank_index.files`, `markdown_parser.parse`, `claims.parse_claims`/`strip_claims_block`,
  `evidence.body_hash`, `inbox_questions.decay_question`, `episode_ids.timestamp_sort_key`,
  `graph_builder.summarize`, `text_fold` (tests).

- [ ] **Step 1: Failing tests.** Create `api/tests/test_search_index.py`:

````python
"""G136 — the derived FTS5 index (`api/services/search_index.py`).

Hermetic: throwaway banks under tmp_path, synthetic names only
(alpha-project, bob-example, example.com). Nothing reads a real bank,
`~/.cicada` or the network.
"""
from __future__ import annotations

import subprocess

import pytest

from api.services import bank_index, bank_registry, evidence, markdown_parser, search_index, text_fold


@pytest.fixture(autouse=True)
def _fresh_state():
    bank_index.invalidate()
    search_index.reset()
    yield
    search_index.reset()
    bank_index.invalidate()


def _entity(memory, eid, *, name=None, body="## Summary\nA synthetic fixture.\n", **fm):
    base = {"name": name or eid.replace("-", " ").title(), "type": "concept", "status": "active",
            "confidence": 0.5, "tags": [], "aliases": []}
    base.update(fm)
    markdown_parser.write(memory / "entities" / f"{eid}.md", base, body)


def _episode(memory, eid, body, **fm):
    base = {"id": eid, "title": "Untitled", "timestamp": "2026-09-01T09:00:00+00:00",
            "harness": "claude-code", "session_id": "ses_2026-09-01_abcd1234", "processed": True}
    base.update(fm)
    markdown_parser.write(memory / "episodes" / f"{eid}.md", base, body)


def _bank(tmp_path):
    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True)
    return memory


def _ids(reader, table, q):
    return [d for d, _ in reader.ranked(table, search_index.match_expression(text_fold.query_tokens(q)), 20)]


def _refs(memory, table, q):
    with search_index.Reader(memory) as r:
        docs = r.docs(_ids(r, table, q))
    return sorted(d.ref for d in docs.values())


def test_passage_spans_tile_the_body_exactly():
    body = "\n".join(f"user: line {i} " + "word " * (i % 40) for i in range(120))
    spans = search_index.passage_spans(body)
    assert "".join(body[s:e] for s, e in spans) == body
    assert all(e - s <= search_index.PASSAGE_CHARS for s, e in spans)
    assert all(body[e - 1] == "\n" for s, e in spans[:-1]), "a window ends on a turn boundary when one is near"
    assert search_index.passage_spans("") == []


def test_names_aliases_diacritics_and_prefixes_are_found(tmp_path):
    memory = _bank(tmp_path)
    _entity(memory, "zurich-office", name="Zürich Office", aliases=["HQ", "headquarters"])
    _entity(memory, "alpha-project", type="project")
    _entity(memory, "alpha-dropped", status="dropped")
    search_index.rebuild(memory)
    assert _refs(memory, "ent", "zur") == ["zurich-office"]
    assert _refs(memory, "ent", "Zurich") == ["zurich-office"]
    assert _refs(memory, "ent", "headq") == ["zurich-office"], "aliases are indexed (R3 P1)"
    assert _refs(memory, "ent", "alpha proj") == ["alpha-project"], "every token is a word-start prefix, ANDed"
    assert _refs(memory, "ent", "alpha zurich") == []
    assert _refs(memory, "ent", "alpha") == ["alpha-project"], "a dropped page is never indexed (R7)"


def test_episode_passages_carry_exact_offsets_into_the_evidence_text(tmp_path):
    memory = _bank(tmp_path)
    filler = "\n".join(f"user: unrelated line {i}" for i in range(80))
    body = f"{filler}\nassistant: we moved the index to sqlite-vec so search is fast\n{filler}"
    _episode(memory, "ep_2026-09-01_001", body, title="Index choice")
    search_index.rebuild(memory)
    text = evidence.source_text(memory, "ep_2026-09-01_001")
    with search_index.Reader(memory) as r:
        rows = r.passages(search_index.match_expression(["sqlite"]), 5, recent_first=False)
        assert len(rows) == 1
        rowid, doc_id, start, end, _ = rows[0]
        assert "sqlite-vec" in text[start:end]
        assert r.passage_text([rowid])[rowid] == text[start:end]
        doc = r.docs([doc_id])[doc_id]
    assert doc.ref == "ep_2026-09-01_001"
    assert doc.meta["hash"] == evidence.body_hash(text)
    assert doc.meta["conversation_id"] == "ses_2026-09-01_abcd1234"


def test_superseded_claims_are_indexed_as_history(tmp_path):
    memory = _bank(tmp_path)
    body = (
        "## Summary\nA person.\n\n```claims\n"
        "- id: clm_old\n  text: \"bob-example lives in Lisbon\"\n  subject: bob-example\n"
        "  predicate: lives_in\n  object: Lisbon\n  valid_to: '2026-05-01'\n  superseded_by: clm_new\n"
        "- id: clm_new\n  text: \"bob-example lives in Porto\"\n  subject: bob-example\n"
        "  predicate: lives_in\n  object: Porto\n"
        "  evidence:\n  - {episode: ep_2026-09-01_001, start: 0, end: 5, kind: user, hash: abcdef123456}\n"
        "```\n"
    )
    _entity(memory, "bob-example", type="person", body=body)
    search_index.rebuild(memory)
    with search_index.Reader(memory) as r:
        old = r.claims(search_index.match_expression(["lisbon"]), 5)
        new = r.claims(search_index.match_expression(["porto"]), 5)
        by_id = r.claims_by_id(["clm_new"])
    assert [p["id"] for *_, p in old] == ["clm_old"]
    assert old[0][4]["valid_to"] == "2026-05-01" and old[0][4]["superseded_by"] == "clm_new"
    assert new[0][4]["evidence"]["episode"] == "ep_2026-09-01_001"
    assert by_id["clm_new"][1] == "bob-example lives in Porto"
    # The subject's name is a claim column: a claim is reachable by who it is about.
    with search_index.Reader(memory) as r:
        assert len(r.claims(search_index.match_expression(["bob", "porto"]), 5)) == 1


def test_claims_citing_an_episode_come_back_with_that_episodes_span(tmp_path):
    memory = _bank(tmp_path)
    body = (
        "## Summary\nA person.\n\n```claims\n"
        "- id: clm_two\n  text: \"bob-example likes tea\"\n  subject: bob-example\n"
        "  evidence:\n"
        "  - {episode: ep_2026-09-01_001, start: 0, end: 4, kind: user, hash: aaaaaaaaaaaa}\n"
        "  - {episode: ep_2026-09-02_001, start: 10, end: 20, kind: assistant, hash: bbbbbbbbbbbb}\n"
        "- id: clm_none\n  text: \"bob-example is kind\"\n  subject: bob-example\n"
        "  evidence:\n  - {kind: reasoning}\n"
        "```\n"
    )
    _entity(memory, "bob-example", type="person", body=body)
    search_index.rebuild(memory)
    with search_index.Reader(memory) as r:
        cited = r.claims_citing("ep_2026-09-02_001")
        assert r.claims_citing("ep_2026-09-03_001") == []
    assert [(p["id"], span) for _d, _t, p, span in cited] == [
        ("clm_two", {"episode": "ep_2026-09-02_001", "start": 10, "end": 20, "kind": "assistant", "hash": "bbbbbbbbbbbb"})]
    (memory / "entities" / "bob-example.md").unlink()
    search_index.ensure_fresh(memory, max_age_s=0)
    with search_index.Reader(memory) as r:
        assert r.claims_citing("ep_2026-09-02_001") == [], "a deleted page takes its citations with it"


def test_media_pages_index_paper_authors_and_ids_and_stay_out_of_ent(tmp_path):
    memory = _bank(tmp_path)
    _entity(memory, "media-wikiskill", name="WikiSkill", type="media",
            media={"url": "https://example.com/abs/2608.27454", "site": "example.com", "media_type": "url"},
            paper={"authors": ["Ada Example", "Bo Sample"], "arxiv_id": "2608.27454",
                   "doi": "10.1234/example.5678"})
    search_index.rebuild(memory)
    assert _refs(memory, "med", "2608.27454") == ["media-wikiskill"]
    assert _refs(memory, "med", "sample") == ["media-wikiskill"]
    assert _refs(memory, "med", "10.1234/example") == ["media-wikiskill"]
    assert _refs(memory, "ent", "wikiskill") == [], "a media page lives in `med` only"


def test_inbox_decay_items_index_the_question_they_are_served_as(tmp_path):
    memory = _bank(tmp_path)
    markdown_parser.write(memory / "inbox" / "inbox-001.md",
                          {"kind": "decay", "status": "pending", "entity_id": "beta-project",
                           "entity_name": "Beta Project", "created_date": "2026-08-01"}, "ctx")
    search_index.rebuild(memory)
    with search_index.Reader(memory) as r:
        doc = next(iter(r.docs(_ids(r, "inb", "still track")).values()))
    assert doc.ref == "inbox-001"
    assert doc.meta["question"] == "Still tracking Beta Project?"


def test_ensure_fresh_picks_up_new_and_deleted_files_without_a_rebuild(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    _entity(memory, "alpha-project")
    search_index.rebuild(memory)
    monkeypatch.setattr(search_index, "_full_build", lambda *a, **k: pytest.fail("incremental, not a rebuild"))
    _entity(memory, "bob-example", type="person")
    assert search_index.ensure_fresh(memory, max_age_s=0) == "ready"
    assert _refs(memory, "ent", "bob") == ["bob-example"]
    (memory / "entities" / "bob-example.md").unlink()
    assert search_index.ensure_fresh(memory, max_age_s=0) == "ready"
    assert _refs(memory, "ent", "bob") == []


def test_ensure_fresh_throttles_the_staleness_scan(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    _entity(memory, "alpha-project")
    search_index.rebuild(memory)
    scans = []
    real = search_index._diff
    monkeypatch.setattr(search_index, "_diff", lambda *a: scans.append(1) or real(*a))
    assert search_index.ensure_fresh(memory) == "ready"   # within the TTL of the build
    assert scans == []
    assert search_index.ensure_fresh(memory, max_age_s=0) == "ready"
    assert scans == [1]


def test_a_bulk_change_is_caught_up_in_the_background(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    search_index.rebuild(memory)
    monkeypatch.setattr(search_index, "INLINE_REFRESH_LIMIT", 2)
    for i in range(3):
        _entity(memory, f"bulk-{i}")
    assert search_index.ensure_fresh(memory, max_age_s=0) == "stale"
    assert search_index.wait_idle(memory, timeout=10)
    assert search_index.ensure_fresh(memory, max_age_s=0) == "ready"
    assert _refs(memory, "ent", "bulk") == ["bulk-0", "bulk-1", "bulk-2"]


def test_deleting_the_file_triggers_a_rebuild_never_an_error(tmp_path):
    memory = _bank(tmp_path)
    _entity(memory, "alpha-project")
    search_index.rebuild(memory)
    for suffix in ("", "-wal", "-shm"):
        path = memory / f"{search_index.DB_FILE}{suffix}"
        if path.exists():
            path.unlink()
    assert search_index.ensure_fresh(memory) == "building"
    assert search_index.wait_idle(memory, timeout=10)
    assert search_index.ensure_fresh(memory) == "ready"
    assert _refs(memory, "ent", "alpha") == ["alpha-project"]


def test_a_corrupt_file_is_discarded_and_rebuilt(tmp_path):
    memory = _bank(tmp_path)
    _entity(memory, "alpha-project")
    (memory / search_index.DB_FILE).write_bytes(b"this is not a sqlite database" * 100)
    assert search_index.ensure_fresh(memory, wait=True) == "ready"
    assert _refs(memory, "ent", "alpha") == ["alpha-project"]


def test_a_schema_change_rebuilds(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    _entity(memory, "alpha-project")
    search_index.rebuild(memory)
    search_index.reset()
    monkeypatch.setattr(search_index, "SCHEMA_VERSION", "999")
    built = []
    real = search_index._full_build
    monkeypatch.setattr(search_index, "_full_build", lambda *a: built.append(1) or real(*a))
    assert search_index.ensure_fresh(memory, wait=True) == "ready"
    assert built == [1]


def test_two_refreshes_of_one_file_never_duplicate_rows(tmp_path):
    """Two processes (the API now, the MCP server later) can both see a file
    as changed; deleting by doc_key inside the transaction keeps one copy."""
    memory = _bank(tmp_path)
    _entity(memory, "alpha-project")
    search_index.rebuild(memory)
    _entity(memory, "alpha-project", body="## Summary\nRewritten.\n")
    state = search_index._state(memory)
    stale = dict(state.stamps)
    changed, removed = search_index._diff(memory, stale)
    search_index._refresh(memory, state, changed, removed)
    search_index._refresh(memory, state, changed, removed)
    with search_index.Reader(memory) as r:
        assert r.count("ent", search_index.match_expression(["alpha"])) == 1


def test_one_odd_page_never_costs_the_build(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    _entity(memory, "alpha-project", confidence="high")  # hand-edited, not a number
    _entity(memory, "bob-example", body="## Summary\nEXPLODE\n")
    _entity(memory, "zurich-office")
    real = search_index.summarize
    monkeypatch.setattr(search_index, "summarize", lambda text: 1 / 0 if "EXPLODE" in text else real(text))
    search_index.rebuild(memory)
    assert _refs(memory, "ent", "alpha") == ["alpha-project"], "a bad number reads as 0.0, the page stays"
    assert _refs(memory, "ent", "zurich") == ["zurich-office"]
    assert _refs(memory, "ent", "bob") == [], "the page that raised is skipped, its rows rolled back"


def test_a_reader_never_creates_the_file(tmp_path):
    import sqlite3

    memory = _bank(tmp_path)
    with pytest.raises(sqlite3.OperationalError):
        search_index.Reader(memory)
    assert not (memory / search_index.DB_FILE).exists()


def test_ensure_fresh_is_unavailable_for_a_directory_that_is_not_a_bank(tmp_path):
    assert search_index.ensure_fresh(tmp_path / "nope", wait=True) == "unavailable"
    assert not (tmp_path / "nope" / search_index.DB_FILE).exists()


def _git(memory, *args):
    return subprocess.run(["git", "-C", str(memory), *args], check=True, capture_output=True, text=True)


def test_the_index_is_never_tracked_by_git(tmp_path):
    memory = _bank(tmp_path)
    _entity(memory, "alpha-project")
    for args in (["init", "-q"], ["config", "user.email", "t@example.com"], ["config", "user.name", "t"],
                 ["add", "-A"], ["commit", "-q", "-m", "seed"]):
        _git(memory, *args)
    search_index.rebuild(memory)
    assert (memory / search_index.DB_FILE).exists()
    assert _git(memory, "status", "--porcelain").stdout == "", "never tracked, never dirties the tree"
    _git(memory, "add", "-A")
    assert _git(memory, "diff", "--cached", "--name-only").stdout == ""
    assert _git(memory, "check-ignore", "-q", search_index.DB_FILE).returncode == 0


def test_ensure_derived_excluded_is_idempotent_and_needs_a_git_dir(tmp_path):
    memory = _bank(tmp_path)
    assert bank_registry.ensure_derived_excluded(memory) is False, "no .git: nothing to protect"
    _git(memory, "init", "-q")
    assert bank_registry.ensure_derived_excluded(memory) is True
    first = (memory / ".git" / "info" / "exclude").read_text(encoding="utf-8")
    assert bank_registry.ensure_derived_excluded(memory) is False
    assert (memory / ".git" / "info" / "exclude").read_text(encoding="utf-8") == first
    assert all(name in first.splitlines() for name in bank_registry.DERIVED_ARTIFACTS)


def test_a_worktree_bank_is_excluded_through_its_common_git_dir(tmp_path):
    """A bank checked out as a git worktree has a `.git` FILE; git reads the
    exclude file from the common git dir, and so must we (G136 R2)."""
    main = tmp_path / "main"
    main.mkdir()
    for args in (["init", "-q"], ["config", "user.email", "t@example.com"], ["config", "user.name", "t"],
                 ["commit", "-q", "--allow-empty", "-m", "seed"],
                 ["worktree", "add", "-q", str(tmp_path / "bank")]):
        _git(main, *args)
    bank = tmp_path / "bank"
    assert (bank / ".git").is_file()
    assert bank_registry.ensure_derived_excluded(bank) is True
    assert _git(bank, "check-ignore", "-q", search_index.DB_FILE).returncode == 0


def test_a_new_bank_gitignore_lists_the_search_index(tmp_path):
    bank_registry.scaffold_bank(tmp_path / "fresh", git_init=False)
    lines = (tmp_path / "fresh" / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert {"search_index.db", "search_index.db-wal", "search_index.db-shm"} <= set(lines)
````

- [ ] **Step 2: Run, expect FAIL.**
  `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_search_index.py -q -p no:cacheprovider`
  → collection error, `ImportError: cannot import name 'search_index'`.

- [ ] **Step 3: Implement — `bank_registry`.** Add `from loguru import logger` after `import yaml`.
  Replace

```python
DERIVED_ARTIFACTS = (
    "vector_index.db",
    "vector_index.db-wal",
    "vector_index.db-shm",
)
```

with

```python
DERIVED_ARTIFACTS = (
    "vector_index.db",
    "vector_index.db-wal",
    "vector_index.db-shm",
    # G136: the FTS5 lexical index (`search_index.py`) — same rule, same
    # directory, same reason.
    "search_index.db",
    "search_index.db-wal",
    "search_index.db-shm",
)

_EXCLUDE_HEADER = "# Cicada: derived, rebuildable artifacts - never versioned (G99, G136)"
```

Insert, directly above the `# --- Resolution (the load-bearing path) ---` banner:

```python
def _git_dir(path: Path) -> Path | None:
    """The directory git reads this bank's ``info/exclude`` from, or None.

    Usually ``<bank>/.git``. A bank checked out as a git worktree or a
    submodule has a ``.git`` FILE (``gitdir: <path>``) instead, and a
    worktree shares ``info/exclude`` through its common dir
    (``<gitdir>/commondir``). Missing that would leave the index unprotected
    in exactly the layouts nobody tests (G136 R2; portability).
    """
    dot = Path(path) / ".git"
    if dot.is_dir():
        return dot
    try:
        head = dot.read_text(encoding="utf-8").strip() if dot.is_file() else ""
        if not head.startswith("gitdir:"):
            return None
        git_dir = (dot.parent / head[len("gitdir:"):].strip()).resolve()
        common = git_dir / "commondir"
        if common.is_file():
            git_dir = (git_dir / common.read_text(encoding="utf-8").strip()).resolve()
    except OSError:
        return None
    return git_dir if git_dir.is_dir() else None


def ensure_derived_excluded(path: Path) -> bool:
    """Make git ignore every derived artifact in this bank, via
    ``.git/info/exclude``. Returns True when it had to add a line.

    Why the exclude file and not ``.gitignore`` (G136 R2): the append
    branch in :func:`scaffold_bank` only fires when ``vector_index.db`` is
    missing from ``.gitignore``, so an existing bank would never learn a NEW
    derived name — and teaching it through ``.gitignore`` means dirtying a
    tracked file that the next ``git add -A`` writer sweeps into its own
    commit under the wrong author (the G85-class smear), or that trips the
    Sleep tail's clean-tree guard. ``.git/info/exclude`` is never tracked,
    never dirties the tree, and ``git add -A`` / ``git status`` honour it.
    New banks still get every name in ``.gitignore`` (``_BANK_GITIGNORE``) so
    the rule travels with a copied bank; this covers the ones that exist.

    Idempotent, cheap (one small read), never raises; a bank with no git
    directory has nothing to protect.
    """
    git_dir = _git_dir(path)
    if git_dir is None:
        return False
    exclude = git_dir / "info" / "exclude"
    try:
        text = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
        have = {line.strip() for line in text.splitlines()}
        missing = [name for name in DERIVED_ARTIFACTS if name not in have]
        if not missing:
            return False
        exclude.parent.mkdir(parents=True, exist_ok=True)
        lead = "" if not text or text.endswith("\n") else "\n"
        with exclude.open("a", encoding="utf-8") as fh:
            fh.write(lead + "\n".join([_EXCLUDE_HEADER, *missing]) + "\n")
        return True
    except OSError as exc:
        logger.warning(f"bank_registry: could not update .git/info/exclude ({exc})")
        return False
```

At the very end of `scaffold_bank` — after the `if git_init and not (path / ".git").exists():`
block's `except (subprocess.CalledProcessError, FileNotFoundError): … pass` — add, at function
indentation:

```python

    # G136: every derived name is excluded even in a bank whose .gitignore
    # predates it (see ensure_derived_excluded for why not .gitignore).
    ensure_derived_excluded(path)
```

- [ ] **Step 4: Implement — the index.** Create `api/services/search_index.py`:

````python
"""G136 — the derived full-text index: SQLite FTS5 beside the vector index.

Round-3 spec decision 7 and design §3.9 item 3. The vector index answers
"what is this *like*"; nothing answered "where did I *type* this" — the
keyword legs were whole-query substring scans that never read ``aliases``
(R3 P1), the ``/search`` fallback re-parsed every entity file per request
(R6 §4.2), and no path searched claims or conversation text at all. This
module is the lexical half: one SQLite database of FTS5 tables over entity
names + aliases + prose, claims (current AND superseded, so a query can show
"was X until <date>", R3 P4), episode titles + passages with offsets into
the evidence text (G118), media/paper metadata, and inbox questions.

Rails this module enforces rather than documents:

* **Derived and disposable** (TODO ruling 3). Markdown+git is the only
  truth; every row here is recomputed from a file. Deleting
  ``search_index.db`` costs one rebuild (3–6 s of CPU for 2,000 entities and
  1,500 episodes, measured 2026-09-23) and never a fact. A missing, corrupt
  or schema-mismatched file is rebuilt, never an error.
* **Never tracked** (G99a). The file lives in the bank directory beside
  ``vector_index.db`` — the caller passes the ACTIVE bank's path; this
  module never resolves a bank itself (the split-brain rule) — and
  ``bank_registry.ensure_derived_excluded`` writes ``.git/info/exclude``
  before the file is first created, so ``git add -A`` can never sweep it.
* **Engine-free.** No LLM, no embedding: tokenising is SQLite's own
  ``unicode61 remove_diacritics 2``, the same fold ``text_fold`` applies to
  the query side.
* **The query never persists.** Nothing here logs or stores query text (K9).

Freshness (G136 R3): Sleep rebuilds the whole file beside the vector index;
between cycles every read path calls :func:`ensure_fresh`, which compares
``bank_index``'s ``(mtime_ns, size)`` stamps (one ``scandir`` per directory,
~6 ms warm at 3,500 files) with the stamps recorded here and re-indexes only
what moved — throttled to one check per ``STALENESS_TTL_S``. A burst larger
than ``INLINE_REFRESH_LIMIT`` documents goes to a single background worker so
a keystroke never waits on a bulk import.

Row ids (G136 R5): every FTS row's rowid is ``doc_id << 16 | n``, where
``doc_id`` is the ``docs`` row of the file it came from. A document's rows
are therefore one contiguous rowid range (delete is a range scan), a passage
knows its episode without reading a column (``rowid >> 16`` — which is what
makes the distinct-episode count 2 ms instead of 33 ms), and because a
re-indexed document is re-inserted with a fresh, larger ``doc_id``,
``ORDER BY rowid DESC`` is "most recently written first" for free.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from loguru import logger

from api.services import bank_index, bank_registry, episode_ids, evidence, inbox_questions, markdown_parser
from api.services.claims import parse_claims, strip_claims_block
from api.services.graph_builder import summarize

DB_FILE = "search_index.db"
SCHEMA_VERSION = "1"
TOKENIZER = "unicode61 remove_diacritics 2"
# Prefix indexes for 2-, 3- and 4-character prefixes: type-as-you-go queries
# are mostly that short, and a prefix with no index is a range scan over
# every matching term (adding the 4 cut the 4-character p95 from 22 to 16 ms
# in the layout experiment, 2026-09-23).
PREFIX = "2 3 4"
# Passage size for episode text. Short enough that a hit's span highlights a
# paragraph, not a page; long enough that 1,500 episodes stay ~25k rows.
PASSAGE_CHARS = 600
# Prose indexed per entity / media page. A page longer than this is still
# found by its name, aliases, tags and first 8,000 characters.
BODY_CHARS = 8000
STALENESS_TTL_S = 1.0
INLINE_REFRESH_LIMIT = 64
ROW_BITS = 16
MAX_ROWS_PER_DOC = (1 << ROW_BITS) - 1
INDEXED_SUBDIRS = ("entities", "inbox", "episodes")

# Column layout per table. `bm25()` weights are positional over ALL columns,
# UNINDEXED ones included — `WEIGHTS` is the one place they are written, and
# they mirror QuickMatch's field weights ×10 (title 1.0, alias 0.9,
# keyword 0.7, body 0.4; design §1.2).
_FTS_COLUMNS = {
    "ent": "title, aliases, keywords, body",
    "med": "title, aliases, keywords, body",
    "clm": "title, aliases, keywords, payload UNINDEXED",
    "epi": "title, keywords",
    "pas": "body, s UNINDEXED, e UNINDEXED",
    "inb": "title, aliases, keywords, body",
}
WEIGHTS = {
    "ent": "10.0, 9.0, 7.0, 4.0",
    "med": "10.0, 9.0, 7.0, 4.0",
    "clm": "10.0, 9.0, 7.0, 0.0",
    "epi": "10.0, 7.0",
    "pas": "4.0, 0.0, 0.0",
    "inb": "10.0, 9.0, 7.0, 4.0",
}

_FTS5: bool | None = None


def db_path(memory_path: Path) -> Path:
    return Path(memory_path) / DB_FILE


def fts5_available() -> bool:
    """Whether this Python's SQLite was compiled with FTS5 (checked once)."""
    global _FTS5
    if _FTS5 is None:
        try:
            conn = sqlite3.connect(":memory:")
            try:
                conn.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
                _FTS5 = True
            finally:
                conn.close()
        except sqlite3.Error:
            _FTS5 = False
    return _FTS5


def _schema_tag() -> str:
    # Any change to how rows are cut or tokenised invalidates the file.
    return f"{SCHEMA_VERSION}|{TOKENIZER}|{PREFIX}|{PASSAGE_CHARS}|{BODY_CHARS}"


def match_expression(tokens: list[str]) -> str:
    """FTS5 MATCH text: every token a quoted prefix term, implicit AND.

    Tokens come from ``text_fold.query_tokens`` (alphanumeric only), and the
    quotes make FTS5 read ``AND``/``OR``/``NEAR`` as words, never operators.
    """
    return " ".join(f'"{tok}"*' for tok in tokens)


def passage_spans(body: str, cap: int = PASSAGE_CHARS) -> list[tuple[int, int]]:
    """Contiguous ``(start, end)`` windows that tile ``body`` exactly.

    Offsets are into the episode's evidence text (``parse(...).body``, R1 of
    G118), so ``body[start:end]`` IS the passage and ``/episodes/{id}/span``
    can verify it. A window prefers to end just after a newline in its last
    200 characters (a turn boundary), then after a space, then hard. No
    overlap and no gap: ``"".join(body[s:e] for s, e in spans) == body``,
    which is what lets a semantic chunk be located exactly (search_service).
    """
    spans: list[tuple[int, int]] = []
    start, n = 0, len(body or "")
    while start < n:
        end = min(n, start + cap)
        if end < n:
            cut = body.rfind("\n", max(start + 1, end - 200), end)
            if cut == -1:
                cut = body.rfind(" ", max(start + 1, end - 200), end)
            if cut > start:
                end = cut + 1
        spans.append((start, end))
        start = end
    return spans


def _open(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db), timeout=5.0, isolation_level=None, check_same_thread=False)
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _discard_files(db: Path) -> None:
    """Remove the db AND its WAL/shm siblings — a fresh file next to a stale
    ``-wal`` is how a SQLite database gets corrupted."""
    for suffix in ("", "-wal", "-shm"):
        try:
            Path(f"{db}{suffix}").unlink()
        except FileNotFoundError:
            pass


# --- per-bank process state ---------------------------------------------------


@dataclass
class _BankState:
    lock: threading.Lock = field(default_factory=threading.Lock)
    # doc_key -> (mtime_ns, size) of what the index holds; None = not loaded
    # (or no usable file). Replaced wholesale, never mutated in place, so a
    # reader iterating it never sees it change underneath.
    stamps: dict[str, tuple[int, int]] | None = None
    checked_at: float = float("-inf")
    worker: threading.Thread | None = None


_STATES: dict[str, _BankState] = {}
_STATES_LOCK = threading.Lock()


def _state(memory_path: Path) -> _BankState:
    with _STATES_LOCK:
        return _STATES.setdefault(str(Path(memory_path)), _BankState())


def reset(memory_path: Path | None = None) -> None:
    """Forget cached process state (tests; never needed in production)."""
    with _STATES_LOCK:
        if memory_path is None:
            _STATES.clear()
        else:
            _STATES.pop(str(Path(memory_path)), None)


def invalidate(memory_path: Path) -> None:
    """A reader hit a broken file: the next ``ensure_fresh`` reloads it, and
    a load that fails rebuilds it."""
    _state(memory_path).stamps = None


# --- scanning -----------------------------------------------------------------


def _scan(memory_path: Path) -> dict[str, bank_index.IndexedFile]:
    out: dict[str, bank_index.IndexedFile] = {}
    for subdir in INDEXED_SUBDIRS:
        for f in bank_index.files(memory_path, subdir):
            if subdir == "inbox" and not f.path.name.startswith("inbox-"):
                continue
            out[f"{subdir}/{f.path.name}"] = f
    return out


def _diff(memory_path: Path, stamps: dict[str, tuple[int, int]]):
    current = _scan(memory_path)
    changed = {k: f for k, f in current.items() if stamps.get(k) != (f.mtime_ns, f.size)}
    removed = [k for k in stamps if k not in current]
    return changed, removed


def _ordered(files: dict[str, bank_index.IndexedFile]) -> list[tuple[str, bank_index.IndexedFile]]:
    """Entities, then inbox, then episodes oldest-first — so a full build
    hands the newest conversation the largest ``doc_id`` and prefix mode's
    ``ORDER BY rowid DESC`` starts from the most recent one."""
    def key(item):
        doc_key, f = item
        subdir = doc_key.split("/", 1)[0]
        ts = episode_ids.timestamp_sort_key(f.frontmatter.get("timestamp")) if subdir == "episodes" else ""
        return (INDEXED_SUBDIRS.index(subdir), ts, doc_key)

    return sorted(files.items(), key=key)


def _load_stamps(db: Path) -> dict[str, tuple[int, int]] | None:
    if not db.exists():
        return None
    try:
        conn = _open(db)
        try:
            row = conn.execute("SELECT value FROM meta WHERE key = 'schema'").fetchone()
            if not row or row[0] != _schema_tag():
                return None
            return {k: (m, s) for k, m, s in conn.execute("SELECT doc_key, mtime_ns, size FROM docs")}
        finally:
            conn.close()
    except sqlite3.DatabaseError:
        return None


# --- writing ------------------------------------------------------------------


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute(
        "CREATE TABLE docs (id INTEGER PRIMARY KEY, doc_key TEXT NOT NULL UNIQUE, "
        "kind TEXT NOT NULL, ref TEXT NOT NULL, mtime_ns INTEGER NOT NULL, "
        "size INTEGER NOT NULL, meta TEXT NOT NULL)"
    )
    conn.execute("CREATE INDEX docs_by_ref ON docs(kind, ref)")
    conn.execute("CREATE TABLE claim_ref (claim_id TEXT PRIMARY KEY, row INTEGER NOT NULL)")
    conn.execute("CREATE INDEX claim_ref_by_row ON claim_ref(row)")
    # Every evidence SPAN of every claim (G118), keyed by the episode it
    # points into — design §3.9 item 3's `claims(…, evidence_episode, start,
    # end, kind, hash)`, and what `GET /episodes/{id}/citations` (Track P, P4)
    # reads instead of parsing every page that might cite an episode.
    conn.execute(
        "CREATE TABLE claim_evidence (row INTEGER NOT NULL, episode TEXT NOT NULL, "
        "s INTEGER NOT NULL, e INTEGER NOT NULL, kind TEXT NOT NULL, hash TEXT NOT NULL)"
    )
    conn.execute("CREATE INDEX claim_evidence_by_episode ON claim_evidence(episode)")
    conn.execute("CREATE INDEX claim_evidence_by_row ON claim_evidence(row)")
    for table, columns in _FTS_COLUMNS.items():
        conn.execute(
            f"CREATE VIRTUAL TABLE {table} USING fts5({columns}, "
            f"tokenize='{TOKENIZER}', prefix='{PREFIX}')"
        )


def _str_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if str(v or "").strip()]


def _float(value) -> float:
    # A hand-edited `confidence: high` must not cost the page its row.
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _insert_doc(conn, doc_key: str, kind: str, ref: str, f, meta: dict) -> int:
    cur = conn.execute(
        "INSERT INTO docs(doc_key, kind, ref, mtime_ns, size, meta) VALUES (?, ?, ?, ?, ?, ?)",
        (doc_key, kind, ref, f.mtime_ns, f.size, json.dumps(meta, default=str)),
    )
    return int(cur.lastrowid)


def _index_entity(conn, doc_key: str, f, fm: dict, body: str) -> None:
    ref = f.path.stem
    prose = strip_claims_block(body)
    etype = str(fm.get("type", "concept") or "concept")
    name = str(fm.get("name") or ref.replace("-", " ").title())
    aliases = _str_list(fm.get("aliases"))
    tags = _str_list(fm.get("tags"))
    meta = {
        "name": name,
        "type": etype,
        "status": str(fm.get("status", "active") or "active"),
        "confidence": _float(fm.get("confidence")),
        "summary": summarize(prose) or "",
        "aliases": aliases[:8],
        "tags": tags[:8],
    }
    if meta["status"] == "dropped":
        # `dropped` = user-dismissed, never resurfaced (the status lifecycle).
        # The docs row keeps the file's stamp, so the page is not re-read on
        # every freshness check, but no FTS row and no claim is written: it
        # can never match, and never inflates a `totals` count (G136 R7/R11).
        _insert_doc(conn, doc_key, "media" if etype == "media" else "entity", ref, f, meta)
        return
    if etype == "media":
        media = fm.get("media") if isinstance(fm.get("media"), dict) else {}
        # Paper metadata in the shape Track F writes (R7 §4: `paper:
        # {arxiv_id, doi, title, authors[]}`), read tolerantly so a paper
        # page is searchable by author or id the moment it exists.
        paper = fm.get("paper") if isinstance(fm.get("paper"), dict) else {}
        authors = _str_list(paper.get("authors"))
        ids = [str(paper.get(k) or "").strip() for k in ("arxiv_id", "doi")]
        site = str(media.get("site") or "")
        channel = str(media.get("channel") or "")
        meta.update(
            site=site,
            channel=channel,
            media_type=str(media.get("media_type") or ""),
            origin=str(fm.get("origin") or ""),
            saved_at=str(fm.get("saved_at") or media.get("saved_at") or ""),
            authors=authors[:6],
            paper=bool(paper) or str(media.get("kind") or "") == "paper",
        )
        doc_id = _insert_doc(conn, doc_key, "media", ref, f, meta)
        conn.execute(
            "INSERT INTO med(rowid, title, aliases, keywords, body) VALUES (?, ?, ?, ?, ?)",
            (
                doc_id << ROW_BITS,
                name,
                " ".join([*aliases, *authors, *[i for i in ids if i]]),
                " ".join(x for x in [*tags, site, channel, meta["media_type"], str(media.get("provider") or "")] if x),
                prose[:BODY_CHARS],
            ),
        )
    else:
        doc_id = _insert_doc(conn, doc_key, "entity", ref, f, meta)
        conn.execute(
            "INSERT INTO ent(rowid, title, aliases, keywords, body) VALUES (?, ?, ?, ?, ?)",
            (doc_id << ROW_BITS, name, " ".join(aliases), " ".join(tags), prose[:BODY_CHARS]),
        )
    # Claims — every one, superseded included (R3 P4: history is searchable
    # here even though the vector claims index holds current claims only).
    for n, claim in enumerate(parse_claims(body)[:MAX_ROWS_PER_DOC], start=1):
        text = (claim.text or "").strip()
        if not text:
            continue
        spans = [e for e in claim.evidence if e.is_span()]
        first = spans[0] if spans else (claim.evidence[0] if claim.evidence else None)
        payload = {
            "id": claim.id,
            "predicate": claim.predicate,
            "object": claim.object,
            "confidence": _float(claim.confidence),
            "valid_from": claim.valid_from,
            "valid_to": claim.valid_to,
            "superseded_by": claim.superseded_by,
            "observer": claim.observer,
            "evidence": first.to_dict() if first else None,
        }
        rowid = (doc_id << ROW_BITS) | n
        conn.execute(
            "INSERT INTO clm(rowid, title, aliases, keywords, payload) VALUES (?, ?, ?, ?, ?)",
            (rowid, text, name, f"{claim.predicate} {claim.object}".strip(), json.dumps(payload, default=str)),
        )
        if claim.id:
            conn.execute("INSERT OR REPLACE INTO claim_ref(claim_id, row) VALUES (?, ?)", (claim.id, rowid))
        for ev in spans:
            conn.execute(
                "INSERT INTO claim_evidence(row, episode, s, e, kind, hash) VALUES (?, ?, ?, ?, ?, ?)",
                (rowid, ev.episode, ev.start, ev.end, ev.kind, ev.hash),
            )


def _index_episode(conn, doc_key: str, f, fm: dict, body: str) -> None:
    ref = f.path.stem  # the evidence doc id (G118 R3) — the file stem, not `fm["id"]`
    meta = {
        "title": str(fm.get("title") or "").strip(),
        "harness": str(fm.get("harness") or "").strip(),
        "origin": str(fm.get("origin") or "").strip(),
        # The same identity rule as session_stats._group (G48).
        "conversation_id": (
            str(fm.get("session_id") or "").strip() or str(fm.get("source_id") or "").strip()
        ),
        "timestamp": str(fm.get("timestamp") or ""),
        "hash": evidence.body_hash(body),
    }
    doc_id = _insert_doc(conn, doc_key, "episode", ref, f, meta)
    conn.execute(
        "INSERT INTO epi(rowid, title, keywords) VALUES (?, ?, ?)",
        (doc_id << ROW_BITS, meta["title"], " ".join(x for x in (meta["harness"], meta["origin"]) if x)),
    )
    for n, (s, e) in enumerate(passage_spans(body)[:MAX_ROWS_PER_DOC], start=1):
        conn.execute(
            "INSERT INTO pas(rowid, body, s, e) VALUES (?, ?, ?, ?)",
            ((doc_id << ROW_BITS) | n, body[s:e], s, e),
        )


def _index_inbox(conn, doc_key: str, f, fm: dict, body: str) -> None:
    ref = f.path.stem
    kind = str(fm.get("kind", "decay") or "decay")
    entity_id = str(fm.get("entity_id") or "")
    entity_name = str(fm.get("entity_name") or "")
    question = str(fm.get("question") or "").strip()
    if not question and kind == "decay":
        # Decay is SERVED as a question and never written as one (G115 R5);
        # index the served words, from the one function that composes them.
        question = inbox_questions.decay_question(entity_name or entity_id, None, str(date.today()))["question"]
    title = question or str(fm.get("title") or entity_name or "")
    meta = {
        "question": title,
        "kind": kind,
        "entity_id": entity_id,
        "entity_name": entity_name,
        "status": str(fm.get("status", "pending") or "pending"),
        "priority": _float(fm.get("priority")),
        "remind_after": str(fm.get("remind_after") or "") or None,
    }
    doc_id = _insert_doc(conn, doc_key, "inbox", ref, f, meta)
    conn.execute(
        "INSERT INTO inb(rowid, title, aliases, keywords, body) VALUES (?, ?, ?, ?, ?)",
        (
            doc_id << ROW_BITS,
            title,
            entity_name,
            " ".join(x for x in (kind, str(fm.get("predicate") or "")) if x),
            str(fm.get("hint") or ""),
        ),
    )


_INDEXERS = {"entities": _index_entity, "episodes": _index_episode, "inbox": _index_inbox}


def _index_doc(conn, doc_key: str, f) -> None:
    """Index one file inside a savepoint: a page that cannot be read or
    indexed is skipped with its partial rows rolled back — one odd file never
    costs the whole build (and never loops a rebuild on every request)."""
    try:
        parsed = markdown_parser.parse(f.path)
    except Exception as exc:
        logger.warning(f"search_index: skipping unreadable {doc_key}: {type(exc).__name__}")
        return
    conn.execute("SAVEPOINT doc")
    try:
        _INDEXERS[doc_key.split("/", 1)[0]](conn, doc_key, f, parsed.frontmatter or {}, parsed.body)
    except Exception as exc:
        conn.execute("ROLLBACK TO doc")
        logger.warning(f"search_index: skipping {doc_key}: {type(exc).__name__}")
    conn.execute("RELEASE doc")


def _delete_doc(conn, doc_key: str) -> None:
    # By doc_key, read inside the transaction — never by a cached id — so two
    # processes refreshing the same file can never leave duplicate rows.
    row = conn.execute("SELECT id FROM docs WHERE doc_key = ?", (doc_key,)).fetchone()
    if row is None:
        return
    lo = int(row[0]) << ROW_BITS
    hi = lo | MAX_ROWS_PER_DOC
    for table in _FTS_COLUMNS:
        conn.execute(f"DELETE FROM {table} WHERE rowid BETWEEN ? AND ?", (lo, hi))
    conn.execute("DELETE FROM claim_ref WHERE row BETWEEN ? AND ?", (lo, hi))
    conn.execute("DELETE FROM claim_evidence WHERE row BETWEEN ? AND ?", (lo, hi))
    conn.execute("DELETE FROM docs WHERE id = ?", (row[0],))


def _write(db: Path, fn) -> None:
    conn = _open(db)
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            fn(conn)
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()


def _full_build(memory_path: Path, state: _BankState) -> int:
    db = db_path(memory_path)
    # Excluded BEFORE the file can exist: the order is the whole rail (G99a).
    bank_registry.ensure_derived_excluded(memory_path)
    files = _scan(memory_path)

    def build(conn):
        for table in (*_FTS_COLUMNS, "claim_ref", "claim_evidence", "docs", "meta"):
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        _create_schema(conn)
        for doc_key, f in _ordered(files):
            _index_doc(conn, doc_key, f)
        conn.execute("INSERT INTO meta(key, value) VALUES ('schema', ?)", (_schema_tag(),))

    def attempt():
        conn = _open(db)
        try:
            conn.execute("PRAGMA journal_mode=WAL").fetchone()
        finally:
            conn.close()
        _write(db, build)

    try:
        attempt()
    except sqlite3.OperationalError:
        raise  # locked or busy: a real, valid file — never discard it
    except sqlite3.DatabaseError:
        # Not a database, or damaged: disposable means start over.
        _discard_files(db)
        attempt()
    state.stamps = {k: (f.mtime_ns, f.size) for k, f in files.items()}
    state.checked_at = time.monotonic()
    logger.info(f"search_index: rebuilt ({len(files)} documents)")
    return len(files)


def _refresh(memory_path: Path, state: _BankState, changed: dict, removed: list[str]) -> None:
    def apply(conn):
        for doc_key in [*removed, *changed]:
            _delete_doc(conn, doc_key)
        for doc_key, f in _ordered(changed):
            _index_doc(conn, doc_key, f)

    _write(db_path(memory_path), apply)
    stamps = dict(state.stamps or {})
    for doc_key in removed:
        stamps.pop(doc_key, None)
    for doc_key, f in changed.items():
        stamps[doc_key] = (f.mtime_ns, f.size)
    state.stamps = stamps
    state.checked_at = time.monotonic()


# --- freshness ----------------------------------------------------------------


def _is_bank(memory_path: Path) -> bool:
    return (memory_path / "entities").is_dir() or (memory_path / "episodes").is_dir()


def ensure_fresh(memory_path: Path, *, wait: bool = False, max_age_s: float | None = None) -> str:
    """Bring the index up to date with the markdown; return its state.

    ``"ready"`` — the index matches the files (within ``max_age_s``);
    ``"stale"`` — served as-is while a background worker catches up (a bulk
    change, or a builder holds the lock); ``"building"`` — no usable index
    yet, a background build started (callers fall back to ``bank_index``);
    ``"unavailable"`` — no FTS5, not a bank, or an error (logged, never
    raised: the index must never be the reason a request fails).

    ``wait=True`` (Sleep, the background worker, tests) does all the work
    inline instead of deferring any of it.
    """
    memory_path = Path(memory_path)
    if not fts5_available() or not _is_bank(memory_path):
        return "unavailable"
    state = _state(memory_path)
    db = db_path(memory_path)
    ttl = STALENESS_TTL_S if max_age_s is None else max_age_s
    try:
        if not db.exists():
            state.stamps = None
        if state.stamps is None:
            state.stamps = _load_stamps(db)
        if state.stamps is None:
            if not wait:
                _spawn(memory_path, state)
                return "building"
            with state.lock:
                if state.stamps is None or not db.exists():
                    state.stamps = _load_stamps(db)
                    if state.stamps is None:
                        _full_build(memory_path, state)
            return "ready"
        if time.monotonic() - state.checked_at < ttl:
            return "ready"
        changed, removed = _diff(memory_path, state.stamps)
        if not changed and not removed:
            state.checked_at = time.monotonic()
            return "ready"
        if not wait and len(changed) + len(removed) > INLINE_REFRESH_LIMIT:
            _spawn(memory_path, state)
            return "stale"
        # Never queue a keystroke behind a build: a busy lock means "serve
        # what is there" (the builder will leave it fresh).
        if not state.lock.acquire(blocking=wait):
            return "stale"
        try:
            changed, removed = _diff(memory_path, state.stamps)
            if changed or removed:
                _refresh(memory_path, state, changed, removed)
            else:
                state.checked_at = time.monotonic()
        finally:
            state.lock.release()
        return "ready"
    except Exception as exc:
        logger.warning(f"search_index: freshness check failed ({type(exc).__name__}: {exc})")
        return "unavailable"


def rebuild(memory_path: Path) -> int:
    """Full rebuild — Sleep's call, beside the vector index. Raises on
    failure so the cycle can record it as an index warning."""
    memory_path = Path(memory_path)
    if not fts5_available() or not _is_bank(memory_path):
        return 0
    state = _state(memory_path)
    with state.lock:
        return _full_build(memory_path, state)


def _background(memory_path: Path) -> None:
    ensure_fresh(memory_path, wait=True, max_age_s=0)


def _spawn(memory_path: Path, state: _BankState) -> None:
    with _STATES_LOCK:
        if state.worker is not None and state.worker.is_alive():
            return
        worker = threading.Thread(
            target=_background, args=(memory_path,), name="cicada-search-index", daemon=True
        )
        state.worker = worker
    worker.start()


def warm_in_background(memory_path: Path) -> None:
    """Build or catch up off the caller's thread (lifespan, bank switch).
    Never raises, never blocks."""
    memory_path = Path(memory_path)
    if fts5_available() and _is_bank(memory_path):
        _spawn(memory_path, _state(memory_path))


def wait_idle(memory_path: Path, timeout: float = 30.0) -> bool:
    """Join the background worker, if any (tests and Sleep's hand-off)."""
    worker = _state(memory_path).worker
    if worker is not None:
        worker.join(timeout)
        return not worker.is_alive()
    return True


# --- reading ------------------------------------------------------------------


@dataclass(frozen=True)
class Doc:
    id: int
    kind: str
    ref: str
    meta: dict


class Reader:
    """One read connection for one search. Every method returns plain rows;
    ranking, fusion and wire shapes live in ``search_service``."""

    def __init__(self, memory_path: Path):
        # `mode=rw`: a reader must never CREATE the file (a plain connect
        # would leave an empty db behind if it vanished since ensure_fresh);
        # a missing file raises here and the caller falls back.
        uri = db_path(memory_path).resolve().as_uri() + "?mode=rw"
        self.conn = sqlite3.connect(uri, uri=True, timeout=2.0, check_same_thread=False)
        self.conn.execute("PRAGMA query_only=ON")

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Reader":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def ranked(self, table: str, match: str, limit: int, *, recent_first: bool = False) -> list[tuple[int, float]]:
        """``[(doc_id, bm25)]`` best first — bm25 is lower-is-better. With
        ``recent_first`` (prefix mode's passage leg) rows come newest-written
        first and bm25 is not computed at all: 0.4 ms instead of 33 ms for a
        two-letter prefix over 25k passages (measured)."""
        if recent_first:
            sql = f"SELECT rowid >> {ROW_BITS}, 0.0 FROM {table} WHERE {table} MATCH ? ORDER BY rowid DESC LIMIT ?"
        else:
            sql = (
                f"SELECT rowid >> {ROW_BITS}, bm25({table}, {WEIGHTS[table]}) AS r "
                f"FROM {table} WHERE {table} MATCH ? ORDER BY r LIMIT ?"
            )
        return [(int(i), float(r)) for i, r in self.conn.execute(sql, (match, int(limit)))]

    def count(self, table: str, match: str) -> int:
        return int(self.conn.execute(f"SELECT count(*) FROM {table} WHERE {table} MATCH ?", (match,)).fetchone()[0])

    def count_episodes(self, match: str) -> int:
        """Distinct episodes matched by title OR passage — read off rowids,
        never a column (2 ms at a two-letter prefix, measured)."""
        sql = (
            f"SELECT count(*) FROM (SELECT rowid >> {ROW_BITS} FROM pas WHERE pas MATCH ?1 "
            f"UNION SELECT rowid >> {ROW_BITS} FROM epi WHERE epi MATCH ?1)"
        )
        return int(self.conn.execute(sql, (match,)).fetchone()[0])

    def passages(self, match: str, limit: int, *, recent_first: bool) -> list[tuple[int, int, int, int, float]]:
        """``[(rowid, doc_id, start, end, bm25)]`` for matching passages."""
        if recent_first:
            sql = (
                f"SELECT rowid, rowid >> {ROW_BITS}, s, e, 0.0 FROM pas WHERE pas MATCH ? "
                f"ORDER BY rowid DESC LIMIT ?"
            )
        else:
            sql = (
                f"SELECT rowid, rowid >> {ROW_BITS}, s, e, bm25(pas, {WEIGHTS['pas']}) AS r "
                f"FROM pas WHERE pas MATCH ? ORDER BY r LIMIT ?"
            )
        return [(int(a), int(b), int(s), int(e), float(r)) for a, b, s, e, r in self.conn.execute(sql, (match, int(limit)))]

    def claims(self, match: str, limit: int) -> list[tuple[int, int, float, str, dict]]:
        """``[(rowid, doc_id, bm25, text, payload)]`` for matching claims."""
        sql = (
            f"SELECT rowid, rowid >> {ROW_BITS}, bm25(clm, {WEIGHTS['clm']}) AS r, title, payload "
            f"FROM clm WHERE clm MATCH ? ORDER BY r LIMIT ?"
        )
        return [(int(a), int(b), float(r), t, json.loads(p or "{}")) for a, b, r, t, p in self.conn.execute(sql, (match, int(limit)))]

    def claims_by_id(self, claim_ids: list[str]) -> dict[str, tuple[int, str, dict]]:
        """``{claim_id: (doc_id, text, payload)}`` — how a vector claim hit
        gets its evidence span without re-reading the page."""
        if not claim_ids:
            return {}
        marks = ",".join("?" * len(claim_ids))
        sql = (
            f"SELECT r.claim_id, c.rowid >> {ROW_BITS}, c.title, c.payload FROM claim_ref r "
            f"JOIN clm c ON c.rowid = r.row WHERE r.claim_id IN ({marks})"
        )
        return {cid: (int(d), t, json.loads(p or "{}")) for cid, d, t, p in self.conn.execute(sql, claim_ids)}

    def claims_citing(self, episode_id: str) -> list[tuple[int, str, dict, dict]]:
        """``[(doc_id, text, payload, span)]`` — every claim with an evidence
        span into ``episode_id``, with THAT span (not the claim's first one).
        The read Track P's ``GET /episodes/{id}/citations`` needs (P4)."""
        sql = (
            f"SELECT c.rowid >> {ROW_BITS}, c.title, c.payload, x.episode, x.s, x.e, x.kind, x.hash "
            f"FROM claim_evidence x JOIN clm c ON c.rowid = x.row WHERE x.episode = ? ORDER BY x.row, x.s"
        )
        return [
            (int(d), t, json.loads(p or "{}"), {"episode": ep, "start": int(s), "end": int(e), "kind": k, "hash": h})
            for d, t, p, ep, s, e, k, h in self.conn.execute(sql, (episode_id,))
        ]

    def docs(self, ids: list[int]) -> dict[int, Doc]:
        if not ids:
            return {}
        marks = ",".join("?" * len(ids))
        rows = self.conn.execute(f"SELECT id, kind, ref, meta FROM docs WHERE id IN ({marks})", list(ids))
        return {int(i): Doc(int(i), k, r, json.loads(m or "{}")) for i, k, r, m in rows}

    def docs_by_ref(self, kinds: tuple[str, ...], refs: list[str]) -> dict[str, Doc]:
        if not refs:
            return {}
        kmarks = ",".join("?" * len(kinds))
        rmarks = ",".join("?" * len(refs))
        rows = self.conn.execute(
            f"SELECT id, kind, ref, meta FROM docs WHERE kind IN ({kmarks}) AND ref IN ({rmarks})",
            [*kinds, *refs],
        )
        return {r: Doc(int(i), k, r, json.loads(m or "{}")) for i, k, r, m in rows}

    def column(self, table: str, column: str, doc_ids: list[int]) -> dict[int, str]:
        """One text column of the head row (``n == 0``) of each doc."""
        if not doc_ids:
            return {}
        marks = ",".join("?" * len(doc_ids))
        rows = self.conn.execute(
            f"SELECT rowid >> {ROW_BITS}, {column} FROM {table} WHERE rowid IN ({marks})",
            [d << ROW_BITS for d in doc_ids],
        )
        return {int(d): t or "" for d, t in rows}

    def passage_text(self, rowids: list[int]) -> dict[int, str]:
        if not rowids:
            return {}
        marks = ",".join("?" * len(rowids))
        return {int(r): b or "" for r, b in self.conn.execute(f"SELECT rowid, body FROM pas WHERE rowid IN ({marks})", list(rowids))}

    def episode_passages(self, doc_id: int, *, until: int | None = None) -> list[tuple[int, int, int, str]]:
        """``[(rowid, start, end, text)]`` of one episode in order, up to and
        including rowid ``until`` when given. Passages tile the body from
        offset 0, so the joined texts ARE ``body[:end]`` of the last one."""
        lo = doc_id << ROW_BITS
        hi = lo | MAX_ROWS_PER_DOC if until is None else until
        return [
            (int(r), int(s), int(e), b or "")
            for r, s, e, b in self.conn.execute(
                "SELECT rowid, s, e, body FROM pas WHERE rowid BETWEEN ? AND ? ORDER BY rowid",
                (lo, hi),
            )
        ]
````

- [ ] **Step 5: Run, expect PASS.** Same command as Step 2 → 21 passed. Then the bank tests that touch
  `scaffold_bank`/`duplicate_bank`:
  `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_banks.py api/tests/test_demo_bank.py -q -p no:cacheprovider`
  → green.

- [ ] **Step 6: Full suite.** → 0 failures, **2256 passed**.

- [ ] **Step 7: Commit.**

```bash
cd <worktree> && git add api/services/bank_registry.py api/services/search_index.py api/tests/test_search_index.py && git commit -F - <<'EOF'
feat(search): the derived FTS5 index beside the vector index (G136 S2)

search_index.db per bank: entity names, aliases and prose; every claim,
superseded ones as history; episode titles and passages that tile the
evidence text exactly; media and paper metadata; inbox questions. Six
per-kind FTS5 tables (unicode61 remove_diacritics 2, prefix 2 3 4),
rowid doc_id<<16|n. Derived and disposable (TODO ruling 3): a missing,
corrupt or schema-mismatched file is rebuilt, never an error. Kept fresh
by a bank_index stamp check (inline up to 64 files, a background worker
beyond). Excluded from git through .git/info/exclude before the file
first exists, following a worktree or submodule .git file to the real
git dir; dropped pages are never indexed (G136 R1-R7, R20).

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 3: `/search` rebuilt — threadpool, kinds, totals, spans, prefix and hybrid (S1 + S2, R7–R16, R19, R22)

The endpoint the palette calls, over Task 2's index and the stored vectors. The branch stays shippable:
the old call shape answers with the same seven fields plus additive ones.

**Files:**
- Modify: `api/services/vector_index.py:272-301` (`_knn`), new `search_kinds` before `_search_kind`
  (`:375`)
- Modify: `api/models/schemas.py:796-807` (`SearchHit`, `SearchResponse`)
- Create: `api/services/search_service.py`
- Rewrite: `api/routers/search.py`
- Modify: `api/main.py` (the `# --- Logging setup ---` block, after the
  `logging.getLogger("openai")` line: the access-log filter, R22)
- Test: `api/tests/test_search_service.py` (new)

**Interfaces:**
- Produces `SqliteVecIndexer.search_kinds(query, top_k_by_kind) -> dict[str, list[dict]]`;
  `search_service.KINDS`, `MAX_PER_KIND`, `SNIPPET_CHARS`, `parse_kinds`, `rrf_scores`, `rrf_fuse`,
  `quick_score`, `snippet_window`, `search(memory_path, q, *, kinds, mode, per_kind, freshness_ttl_s,
  embed_fn) -> SearchResponse`, `lexical_entity_hits`, `claim_subject_hits`; the wire above;
  `main._RedactQueryString` on the `uvicorn.access` logger.
- Consumes everything Task 2 produced, `bank_index.files`, `evidence.speaker_kind`,
  `inbox_questions.is_deferred`, `inbox_service._subject_gone`, `text_fold`.

- [ ] **Step 1: Failing tests.** Create `api/tests/test_search_service.py`:

````python
"""G136 — `GET /search` and `search_service` (round-3 design §3.9, §3.10).

Hermetic: a synthetic bank under tmp_path (alpha-project, bob-example,
example.com), a deterministic fake embedder where vectors are needed, no
network, no real model.
"""
from __future__ import annotations

import asyncio
import importlib
import time

import numpy as np
import pytest
from loguru import logger

from api.services import bank_index, evidence, markdown_parser, providers, search_index, search_service, text_fold

EP_PORTO = "ep_2026-09-01_002"


@pytest.fixture(autouse=True)
def _fresh_state():
    bank_index.invalidate()
    search_index.reset()
    yield
    search_index.reset()
    bank_index.invalidate()


def _entity(memory, eid, *, name, body="## Summary\nA synthetic fixture.\n", **fm):
    base = {"name": name, "type": "concept", "status": "active", "confidence": 0.5, "tags": [], "aliases": []}
    base.update(fm)
    markdown_parser.write(memory / "entities" / f"{eid}.md", base, body)


def _bank(tmp_path):
    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True)
    porto_body = "user: I moved to Porto last spring\nassistant: noted"
    markdown_parser.write(memory / "episodes" / f"{EP_PORTO}.md",
                          {"id": EP_PORTO, "title": "Moving notes", "timestamp": "2026-09-01T10:00:00+00:00",
                           "session_id": "ses_2026-09-01_porto001", "harness": "codex"}, porto_body)
    text = evidence.source_text(memory, EP_PORTO)
    start = text.find("I moved to Porto")
    span = {"episode": EP_PORTO, "start": start, "end": start + len("I moved to Porto"),
            "kind": "user", "hash": evidence.body_hash(text)}
    claims = (
        "\n```claims\n"
        "- id: clm_porto\n  text: \"bob-example lives in Porto\"\n  subject: bob-example\n"
        "  predicate: lives_in\n  object: Porto\n  confidence: 0.9\n"
        f"  evidence:\n  - {{episode: {span['episode']}, start: {span['start']}, end: {span['end']}, kind: user, hash: {span['hash']}}}\n"
        "- id: clm_lisbon\n  text: \"bob-example lives in Lisbon\"\n  subject: bob-example\n"
        "  predicate: lives_in\n  object: Lisbon\n  valid_to: '2026-05-01'\n  superseded_by: clm_porto\n"
        "```\n"
    )
    _entity(memory, "bob-example", name="Bob Example", type="person", body="## Summary\nA friend.\n" + claims)
    _entity(memory, "alpha-project", name="Alpha Project", type="project", aliases=["Project A"], tags=["infra"],
            body="## Summary\nThe first project.\n\n## Key Facts\nUses sqlite-vec for retrieval.\n")
    _entity(memory, "alpha-archive", name="Alpha Archive", status="archived")
    _entity(memory, "zurich-office", name="Zürich Office", type="location", aliases=["HQ"])
    _entity(memory, "whiskers", name="Whiskers", body="## Summary\nA cat that sleeps all day.\n")
    _entity(memory, "media-wikiskill", name="WikiSkill paper", type="media",
            media={"url": "https://example.com/abs/2608.27454", "site": "example.com", "media_type": "url"},
            paper={"authors": ["Ada Example", "Bo Sample"], "arxiv_id": "2608.27454"})
    filler = "\n".join(f"user: unrelated line {i}" for i in range(60))
    markdown_parser.write(memory / "episodes" / "ep_2026-09-02_001.md",
                          {"id": "ep_2026-09-02_001", "title": "Index choice", "harness": "claude-code",
                           "timestamp": "2026-09-02T09:00:00+00:00",
                           "session_id": "0f8f1c2a-4b5d-4e6f-8a9b-0c1d2e3f4a5b"},
                          f"{filler}\nassistant: we moved the index to sqlite-vec so search is fast\n{filler}")
    markdown_parser.write(memory / "inbox" / "inbox-001.md",
                          {"kind": "decay", "status": "pending", "entity_id": "alpha-project",
                           "entity_name": "Alpha Project", "created_date": "2026-08-01"}, "ctx")
    markdown_parser.write(memory / "inbox" / "inbox-002.md",
                          {"kind": "conflict", "status": "pending", "entity_id": "alpha-project",
                           "entity_name": "Alpha Project", "question": "Which alpha database?",
                           "remind_after": "2099-01-01", "created_date": "2026-08-01"}, "ctx")
    markdown_parser.write(memory / "inbox" / "inbox-003.md",
                          {"kind": "conflict", "status": "pending", "entity_id": "alpha-archive",
                           "entity_name": "Alpha Archive", "question": "Is alpha archive done?",
                           "created_date": "2026-08-01"}, "ctx")
    search_index.rebuild(memory)
    return memory


def _search(memory, q, **kw):
    kw.setdefault("freshness_ttl_s", 0)
    return search_service.search(memory, q, **kw)


def _by_kind(resp, kind):
    return [h for h in resp.results if h.kind == kind]


# --- pure helpers ---------------------------------------------------------------


def test_parse_kinds_accepts_palette_names_and_keeps_group_order():
    assert search_service.parse_kinds("inbox,papers,beliefs,conversations,entities") == [
        "entity", "claim", "episode", "media", "inbox"]
    assert search_service.parse_kinds(None) == ["entity"]
    assert search_service.parse_kinds(None, "entities,claims") == ["entity", "claim"], "legacy `indexes`"
    assert search_service.parse_kinds("episode", "entities") == ["episode"], "`kinds` wins"
    assert search_service.parse_kinds("nonsense") == ["entity"]


def test_rrf_fuse_matches_the_mcp_helper_exactly():
    mcp = importlib.import_module("mcp.server")
    semantic = [{"entity_id": "a"}, {"entity_id": "b"}, {"entity_id": "c"}]
    keyword = [{"entity_id": "b"}, {"entity_id": "a"}, {"id": "d"}]
    assert search_service.rrf_fuse(semantic, keyword) == mcp._rrf_fuse(semantic, keyword)


def test_quick_score_orders_exact_then_prefix_then_word_start():
    fields = lambda name: [(name, 1.0, "name")]  # noqa: E731
    exact, _ = search_service.quick_score(["alpha"], fields("Alpha"))
    prefix, _ = search_service.quick_score(["alpha"], fields("Alphabet soup"))
    word, _ = search_service.quick_score(["alpha"], fields("Project alpha"))
    body, label = search_service.quick_score(["alpha"], fields("Unrelated"))
    assert exact > prefix > word > body and label == "body"
    assert search_service.quick_score(["hq"], [("Zürich Office", 1.0, "name"), ("HQ", 0.9, "alias")])[1] == "alias"


def test_snippet_window_centres_on_the_match_and_offsets_slice_the_snippet():
    text = ("lorem ipsum " * 40) + "the sqlite-vec index " + ("dolor sit " * 40)
    snippet, offsets = search_service.snippet_window(text, ["sqlite"])
    assert len(snippet) <= search_service.SNIPPET_CHARS + 2
    assert snippet.startswith("…") and snippet.endswith("…")
    assert [snippet[s:e] for s, e in offsets] == ["sqlite"]


# --- the service ---------------------------------------------------------------------


def test_default_call_is_entities_only_in_the_legacy_shape(tmp_path):
    memory = _bank(tmp_path)
    resp = _search(memory, "alpha")
    assert {h.kind for h in resp.results} == {"entity"}
    assert resp.results[0].id == "alpha-project", "live exact-prefix name first"
    assert resp.results[-1].id == "alpha-archive", "archived pages rank after live ones"
    assert resp.totals == {"entity": 2}
    assert resp.index_state == "ready"


def test_kinds_are_honoured_and_totals_are_per_kind(tmp_path):
    memory = _bank(tmp_path)
    resp = _search(memory, "alpha", kinds=search_service.KINDS, mode="prefix")
    kinds = [h.kind for h in resp.results]
    assert kinds == sorted(kinds, key=search_service.KINDS.index), "grouped in the fixed order"
    assert [h.id for h in _by_kind(resp, "inbox")] == ["inbox-001"], "deferred and subject-gone items are not served"
    assert _by_kind(resp, "inbox")[0].name == "Still tracking Alpha Project?"
    assert resp.totals["inbox"] == 1
    assert set(resp.totals) == {"entity", "claim", "episode", "media", "inbox"}


def test_aliases_and_diacritics_find_the_page_and_say_why(tmp_path):
    memory = _bank(tmp_path)
    hq = _search(memory, "hq", mode="prefix").results
    assert [h.id for h in hq] == ["zurich-office"]
    assert hq[0].matched_field == "alias" and hq[0].subtitle == "HQ"
    assert [h.id for h in _search(memory, "zurich", mode="prefix").results] == ["zurich-office"]


def test_media_is_its_own_group_only_when_asked_for(tmp_path):
    memory = _bank(tmp_path)
    legacy = _search(memory, "wikiskill", mode="prefix")
    assert [(h.kind, h.id) for h in legacy.results] == [("entity", "media-wikiskill")]
    split = _search(memory, "wikiskill", kinds=("entity", "media"), mode="prefix")
    assert [(h.kind, h.id) for h in split.results] == [("media", "media-wikiskill")]
    by_author = _search(memory, "sample", kinds=("media",), mode="prefix").results
    assert by_author[0].subtitle == "Ada Example, Bo Sample"
    assert _search(memory, "2608.27454", kinds=("media",), mode="prefix").results[0].id == "media-wikiskill"


def test_claim_hits_carry_their_evidence_span_and_history_ranks_after_the_present(tmp_path):
    memory = _bank(tmp_path)
    claims = _by_kind(_search(memory, "bob lives", kinds=("claim",), mode="prefix"), "claim")
    assert [c.id for c in claims] == ["clm_porto", "clm_lisbon"]
    porto, lisbon = claims
    assert porto.subject_id == "bob-example" and porto.subtitle == "Bob Example"
    text = evidence.source_text(memory, porto.episode_id)
    assert text[porto.start:porto.end] == "I moved to Porto"
    assert porto.hash == evidence.body_hash(text) and porto.evidence_kind == "user"
    assert lisbon.valid_to == "2026-05-01" and lisbon.superseded_by == "clm_porto"


def test_a_page_is_reached_through_one_of_its_claims(tmp_path):
    memory = _bank(tmp_path)
    hits = _search(memory, "porto", mode="prefix").results
    assert [h.id for h in hits] == ["bob-example"]
    assert hits[0].matched_field == "claim" and hits[0].subtitle == "bob-example lives in Porto"
    assert _search(memory, "lisbon", mode="prefix").results == [], "a superseded claim never leads to its subject"


def test_episode_hits_carry_a_verifiable_span_around_the_match(tmp_path):
    memory = _bank(tmp_path)
    [hit] = _by_kind(_search(memory, "sqlite vec", kinds=("episode",), mode="prefix"), "episode")
    text = evidence.source_text(memory, hit.episode_id)
    assert "sqlite-vec" in text[hit.start:hit.end]
    assert text[hit.start:hit.end].startswith("assistant:"), "the span is the matching line"
    assert hit.hash == evidence.body_hash(text) and hit.evidence_kind == "assistant"
    assert hit.conversation_id == "0f8f1c2a-4b5d-4e6f-8a9b-0c1d2e3f4a5b" and hit.harness == "claude-code"
    assert [hit.snippet[s:e] for s, e in hit.snippet_offsets] == ["sqlite", "vec"]
    title = _by_kind(_search(memory, "index choice", kinds=("episode",), mode="prefix"), "episode")[0]
    assert title.matched_field == "name" and title.start is None and title.hash is None, "a title match claims no span"


def test_prefix_mode_never_builds_an_indexer_or_touches_the_embed_cache(tmp_path, monkeypatch):
    memory = _bank(tmp_path)

    class Tripwire(dict):
        def __getitem__(self, key):
            raise AssertionError("prefix mode touched _EMBED_CACHE")

        get = __contains__ = __setitem__ = __getitem__

    class NoIndexer:
        def __init__(self, *a, **k):
            raise AssertionError("prefix mode built a vector indexer")

    monkeypatch.setattr(providers, "_EMBED_CACHE", Tripwire())
    monkeypatch.setattr("api.services.vector_index.SqliteVecIndexer", NoIndexer)
    resp = _search(memory, "alpha", kinds=search_service.KINDS, mode="prefix")
    assert resp.mode == "prefix" and resp.results


def _fake_embed(texts, *, is_query=False):
    """Deterministic: "cat" and "feline" share a direction (the semantic
    link no lexical index can see), "alpha" has its own, every vector has a
    small constant so none is zero."""
    rows = []
    for text in texts:
        words = set(text_fold.words(text))
        v = np.array([1.0 if words & {"cat", "feline"} else 0.0,
                      1.0 if "alpha" in words else 0.0, 0.1], dtype=np.float32)
        rows.append(v / np.linalg.norm(v))
    return np.stack(rows)


def _vectors(memory):
    from api.services.vector_index import SqliteVecIndexer

    indexer = SqliteVecIndexer(memory, embed_fn=_fake_embed)
    indexer.index_entities()
    indexer.index_claims()
    indexer.index_episodes()


def test_hybrid_fuses_the_stored_vectors_and_labels_semantic_only_rows(tmp_path):
    memory = _bank(tmp_path)
    _vectors(memory)
    resp = _search(memory, "feline", mode="hybrid", embed_fn=_fake_embed)
    assert resp.mode == "hybrid"
    assert resp.results[0].id == "whiskers" and resp.results[0].matched_field == "semantic"
    assert resp.totals == {"entity": 0}, "semantic neighbours are ranked, never counted"


def test_hybrid_embeds_the_query_once_for_every_kind(tmp_path):
    memory = _bank(tmp_path)
    _vectors(memory)
    calls = []

    def counting(texts, *, is_query=False):
        calls.append(is_query)
        return _fake_embed(texts, is_query=is_query)

    _search(memory, "alpha", kinds=search_service.KINDS, mode="hybrid", embed_fn=counting)
    assert calls.count(True) == 1


def test_hybrid_keeps_history_after_every_current_claim(tmp_path):
    """G136 R10 in hybrid too: the vector claims index holds current claims
    only, so a superseded claim can only arrive lexically — and RRF alone
    would tie it with the first semantic neighbour. History sinks below
    every current claim before the cut, like the archived tier for pages."""
    memory = _bank(tmp_path)
    _vectors(memory)
    claims = _by_kind(_search(memory, "lisbon", kinds=("claim",), mode="hybrid", embed_fn=_fake_embed), "claim")
    assert [c.id for c in claims] == ["clm_porto", "clm_lisbon"]
    assert claims[0].matched_field == "semantic" and claims[1].valid_to == "2026-05-01"


def test_hybrid_without_a_vector_index_says_lexical(tmp_path):
    memory = _bank(tmp_path)
    resp = _search(memory, "alpha", mode="hybrid")
    assert resp.mode == "lexical" and resp.results[0].id == "alpha-project"


def test_while_the_index_builds_pages_come_from_the_frontmatter_cache(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    monkeypatch.setattr(search_index, "ensure_fresh", lambda *a, **k: "building")
    _search(memory, "hq", mode="prefix")  # warm bank_index
    parses = bank_index.parse_count
    resp = _search(memory, "hq", kinds=("entity", "claim", "episode"), mode="prefix")
    assert bank_index.parse_count == parses, "no page is parsed per request (R6 §4.2)"
    assert [h.id for h in resp.results] == ["zurich-office"]
    assert resp.index_state == "building" and resp.totals == {"entity": 1}


def test_a_broken_index_file_degrades_to_the_fallback_not_a_500(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    monkeypatch.setattr(search_index, "ensure_fresh", lambda *a, **k: "ready")
    # A hand-edited page the fallback must read without a 500 (it builds a
    # meta for every page, matching or not).
    _entity(memory, "odd-page", name="Odd Page", confidence="high")
    (memory / search_index.DB_FILE).write_bytes(b"garbage" * 1000)
    for suffix in ("-wal", "-shm"):
        (memory / f"{search_index.DB_FILE}{suffix}").unlink(missing_ok=True)
    resp = _search(memory, "alpha", mode="prefix")
    assert resp.index_state == "unavailable" and resp.results[0].id == "alpha-project"


def test_the_query_is_never_logged(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    records: list[str] = []
    sink = logger.add(lambda msg: records.append(msg.record["message"]), level="DEBUG")
    try:
        _search(memory, "zebracorn alpha", kinds=search_service.KINDS, mode="hybrid")
        monkeypatch.setattr(search_index, "ensure_fresh", lambda *a, **k: "ready")
        (memory / search_index.DB_FILE).write_bytes(b"garbage" * 1000)
        _search(memory, "zebracorn alpha", mode="prefix")
    finally:
        logger.remove(sink)
    assert records, "the failure path logged something"
    assert not any("zebracorn" in r for r in records)


def test_the_access_log_never_carries_the_query():
    """K9 at the HTTP layer (G136 R22): uvicorn's access log writes the
    request line with its query string; the filter `api.main` attaches
    strips it for the two query-bearing paths and leaves every other line."""
    import logging

    from api import main  # noqa: F401  (importing it attaches the filter)

    access = logging.getLogger("uvicorn.access")
    lines: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record):
            lines.append(record.getMessage())

    handler = Capture(level=logging.INFO)
    saved = (access.level, access.disabled)
    access.addHandler(handler)
    access.setLevel(logging.INFO)
    access.disabled = False
    try:
        for path in ("/search?q=zebracorn&mode=prefix", "/conversations/recent?limit=5&q=zebracorn",
                     "/graph?bank=alpha"):
            access.info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:5000", "GET", path, "1.1", 200)
    finally:
        access.removeHandler(handler)
        access.setLevel(saved[0])
        access.disabled = saved[1]
    assert lines == [
        '127.0.0.1:5000 - "GET /search?… HTTP/1.1" 200',
        '127.0.0.1:5000 - "GET /conversations/recent?… HTTP/1.1" 200',
        '127.0.0.1:5000 - "GET /graph?bank=alpha HTTP/1.1" 200',
    ]


def test_mcp_legs_come_back_in_the_rrf_shape(tmp_path):
    memory = _bank(tmp_path)
    assert search_service.lexical_entity_hits(memory, "hq")[0] == {
        "entity_id": "zurich-office", "source": "keyword",
        "score": pytest.approx(search_service.lexical_entity_hits(memory, "hq")[0]["score"])}
    assert search_service.lexical_entity_hits(memory, "porto") == [], "claim-reached rows are the claim leg's"
    assert search_service.claim_subject_hits(memory, "porto") == [
        {"entity_id": "bob-example", "source": "claim", "score": 0.0}]


# --- the router --------------------------------------------------------------------------


def _client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from api import config, main

    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    return TestClient(main.app), memory


def test_router_keeps_the_old_call_shape_and_speaks_camel_case(tmp_path, monkeypatch):
    client, _memory = _client(tmp_path, monkeypatch)
    old = client.get("/search", params={"q": "alpha", "top_k": 8, "indexes": "entities"})
    assert old.status_code == 200, old.text
    body = old.json()
    first = body["results"][0]
    assert {"id", "name", "type", "status", "confidence", "score", "snippet"} <= set(first)
    assert first["kind"] == "entity" and "snippetOffsets" in first and "matchedField" in first
    assert body["totals"] == {"entity": 2} and body["indexState"] == "ready"
    new = client.get("/search", params={"q": "sqlite", "kinds": "entity,claim,episode,media", "mode": "prefix",
                                        "per_kind": 5}).json()
    assert {h["kind"] for h in new["results"]} == {"entity", "episode"}
    ep = next(h for h in new["results"] if h["kind"] == "episode")
    assert {"episodeId", "conversationId", "start", "end", "hash", "evidenceKind"} <= set(ep)


def test_router_validates_mode_and_per_kind(tmp_path, monkeypatch):
    client, _memory = _client(tmp_path, monkeypatch)
    assert client.get("/search", params={"q": "alpha", "mode": "fuzzy"}).status_code == 422
    assert client.get("/search", params={"q": "alpha", "per_kind": 21}).status_code == 422


def test_search_does_not_block_the_event_loop(tmp_path, monkeypatch):
    """R6 §4.2: /search was blocking work inside `async def`. With the body in
    the threadpool, a concurrent /healthz answers while a slow search runs."""
    import httpx

    from api import main
    from api.routers import search as search_router

    _client(tmp_path, monkeypatch)

    def slow(*a, **k):
        time.sleep(0.6)
        return search_service.SearchResponse(results=[])

    monkeypatch.setattr(search_router.search_service, "search", slow)

    async def run():
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            started = time.perf_counter()
            pending = asyncio.create_task(ac.get("/search", params={"q": "alpha"}))
            await asyncio.sleep(0.05)
            health = await ac.get("/healthz")
            healthz_after = time.perf_counter() - started
            return health, await pending, healthz_after

    health, slow_resp, healthz_after = asyncio.run(run())
    assert health.status_code == 200 and slow_resp.status_code == 200
    assert healthz_after < 0.5
````

- [ ] **Step 2: Run, expect FAIL.**
  `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_search_service.py -q -p no:cacheprovider`
  → collection error, `ImportError: cannot import name 'search_service'`.

- [ ] **Step 3: Implement — one embed for several kinds.** In `api/services/vector_index.py` replace
  the head of `_knn`

```python
    def _knn(
        self, conn: sqlite3.Connection, kind: str, query: str, top_k: int
    ) -> list[dict]:
        import sqlite_vec

        vec_table = f"vec_{kind}"
        meta_table = f"meta_{kind}"
        try:
            qvec = self._embed([query], is_query=True)[0]
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"vector search embed failed ({kind}): {exc}")
            return []
```

with

```python
    def _knn(
        self,
        conn: sqlite3.Connection,
        kind: str,
        query: str,
        top_k: int,
        *,
        qvec: np.ndarray | None = None,
    ) -> list[dict]:
        import sqlite_vec

        vec_table = f"vec_{kind}"
        meta_table = f"meta_{kind}"
        if qvec is None:
            try:
                qvec = self._embed([query], is_query=True)[0]
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"vector search embed failed ({kind}): {exc}")
                return []
```

and insert, directly above `def _search_kind(self, kind: str, query: str, top_k: int)`:

```python
    def search_kinds(self, query: str, top_k_by_kind: dict[str, int]) -> dict[str, list[dict]]:
        """KNN over several kinds with ONE query embedding (G136).

        ``/search``'s hybrid mode wants the entity, claim and episode legs of
        one query at once; three ``search_*`` calls embed the same text three
        times, and the embed is the dominant cost of a warm search (G58). Same
        graceful degrade as :meth:`_search_kind`: a missing db, a missing
        table or a failed embed gives empty lists, never a raise. No
        archived-tier or superseded filtering happens here — the caller ranks.
        """
        out: dict[str, list[dict]] = {kind: [] for kind in top_k_by_kind}
        if not top_k_by_kind or not self.db_path.exists():
            return out
        try:
            qvec = self._embed([query], is_query=True)[0]
        except Exception as exc:  # noqa: BLE001
            # The exception class only: a provider's error can echo its input,
            # and the input is the person's query (K9).
            logger.debug(f"vector search embed failed (search_kinds): {type(exc).__name__}")
            return out
        conn = self._connect()
        try:
            for kind, top_k in top_k_by_kind.items():
                try:
                    out[kind] = self._knn(conn, kind, query, top_k, qvec=qvec)
                except sqlite3.OperationalError as exc:
                    logger.warning(
                        f"vector_index.search_kinds({kind!r}): query failed ({exc}); degrading to []"
                    )
        finally:
            conn.close()
        return out

```

- [ ] **Step 4: Implement — the wire.** In `api/models/schemas.py` replace

```python
class SearchHit(CamelModel):
    id: str
    name: str
    type: str
    status: str
    confidence: float
    score: float = 0.0
    snippet: str = ""


class SearchResponse(CamelModel):
    results: list[SearchHit]
```

with

````python
class SearchHit(CamelModel):
    """One ``GET /search`` row (G136, round-3 design §3.9).

    The first seven fields are the pre-G136 shape and stay required-compatible
    (``GraphSearchHit`` decodes them). Everything after is additive and
    optional. Per ``kind``:

    - ``entity`` / ``media``: ``id`` is the entity id; ``type``/``status``/
      ``confidence`` are the page's; ``subtitle`` is the alias that matched
      (entity), or the authors / site (media).
    - ``claim``: ``id`` is the claim id and ``name`` its text; ``subject_id``
      is the page it lives on, and ``type``/``status`` are that page's;
      ``valid_to``/``superseded_by`` set means history ("was X until …").
    - ``episode``: ``id`` is the episode (evidence doc) id and ``name`` its
      title; ``start``/``end``/``hash`` are a span into the evidence text
      (G118) around the best passage, and ``evidence_kind`` is its speaker.
    - ``inbox``: ``id`` is the inbox item id, ``name`` the question it is
      served as, ``type`` the item's kind, ``subject_id`` its entity.

    ``matched_field`` is ``name | alias | keyword | body | claim | semantic``
    — why this row is here. ``snippet_offsets`` are ``[start, end]`` code-point
    (Unicode scalar) ranges into ``snippet`` to bold. ``score`` orders rows
    within one response and is not comparable across modes.
    """

    id: str
    name: str
    type: str
    status: str
    confidence: float
    score: float = 0.0
    snippet: str = ""
    kind: str = "entity"
    subtitle: str | None = None
    snippet_offsets: list[list[int]] = Field(default_factory=list)
    matched_field: str | None = None
    subject_id: str | None = None
    episode_id: str | None = None
    conversation_id: str | None = None
    harness: str | None = None
    origin: str | None = None
    timestamp: str | None = None
    start: int | None = None
    end: int | None = None
    hash: str | None = None
    evidence_kind: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    superseded_by: str | None = None


class SearchResponse(CamelModel):
    """``totals`` is the exact number of documents per kind that match the
    query LEXICALLY (every token a word-start prefix) — the one countable set,
    so "Show all N" is never a guess. A hybrid response may also carry
    semantic-only neighbours (``matched_field: semantic``), which are ranked,
    not counted. ``mode`` is what actually ran: ``lexical`` when hybrid was
    asked for but no vector index answered. ``index_state`` is
    ``ready | stale | building | unavailable`` (``search_index.ensure_fresh``);
    while it is not ready/stale, only entities and media are served, from the
    frontmatter cache."""

    results: list[SearchHit]
    totals: dict[str, int] = Field(default_factory=dict)
    mode: str = "hybrid"
    index_state: str = "ready"
````

- [ ] **Step 5: Implement — the service.** Create `api/services/search_service.py`:

````python
"""G136 — search everywhere, the server half: lexical + semantic retrieval.

What ``GET /search`` runs (in a threadpool — R6 §4.2 found it blocking the
event loop), and what MCP recall can adopt later without re-deriving it (the
hand-off: ``lexical_entity_hits`` / ``claim_subject_hits`` are the keyword
and claim legs in the exact shape ``mcp/server.py::_rrf_fuse`` reads).

Two modes (round-3 design §3.2):

* ``prefix`` — the palette's per-keystroke pass. FTS5 only: it never builds
  a vector indexer, never embeds, never touches ``providers._EMBED_CACHE``
  (R3 P1: a typeahead must not run EmbeddingGemma per character). Budget
  p95 ≤ 50 ms at 2,000 entities / 1,500 episodes, pinned by
  ``test_search_latency.py``.
* ``hybrid`` — the idle pass. The same lexical legs fused by reciprocal rank
  with the stored vectors (ONE query embedding for every kind,
  ``SqliteVecIndexer.search_kinds``), plus claims as a third entity leg
  mapped to their subject (R3 P2). Budget 200 ms (G58).

Ranking inside a kind mirrors the app's ``QuickMatch`` (design §1.2) over the
fields the index holds — whole field > field prefix > word-start prefix, with
weights name 1.0 / alias 0.9 / keyword 0.7 / body 0.4 — so the palette's
local tier and its server tier never disagree about one name (G136 R7).

Rails: engine-free (no LLM anywhere in search); the query is never logged,
stored or sent to telemetry (K9); a missing or broken index degrades to the
``bank_index`` frontmatter cache and says so in ``index_state``, never a 500.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable, Iterable

from loguru import logger

from api.models.schemas import SearchHit, SearchResponse
from api.services import bank_index, evidence, inbox_questions, inbox_service, search_index, text_fold

KINDS = ("entity", "claim", "episode", "media", "inbox")
_KIND_ALIASES = {
    "entity": "entity", "entities": "entity",
    "claim": "claim", "claims": "claim", "belief": "claim", "beliefs": "claim",
    "episode": "episode", "episodes": "episode", "conversation": "episode", "conversations": "episode",
    "media": "media", "source": "media", "sources": "media", "paper": "media", "papers": "media",
    "inbox": "inbox",
}
MODES = ("prefix", "hybrid")
MAX_PER_KIND = 20
SNIPPET_CHARS = 160
RRF_K = 60
# Candidates read per kind before re-ranking and filtering (the archived
# tier, the media split, fusion), so a filter never starves a group.
CANDIDATE_FACTOR = 4
# Inbox matches read before the visibility filter. An inbox is hundreds of
# items at most, so this is "all of them" in practice — and when it is not,
# the kind's total is omitted rather than guessed.
INBOX_SCAN = 200
_TIERS = 5  # QuickMatch: score = Σ (5 − tier) × weight


def parse_kinds(kinds: str | None, indexes: str | None = None) -> list[str]:
    """``kinds`` csv → canonical kinds, in the fixed group order.

    Accepts plural and palette names (``conversations``, ``beliefs``,
    ``sources``, ``papers``, …). The legacy ``indexes`` parameter — sent by
    ``APIClient.search`` as ``indexes=entities`` and never read before G136 —
    is honoured only when ``kinds`` is absent. Nothing recognised → today's
    behaviour, entities only.
    """
    raw = kinds if kinds is not None and kinds.strip() else (indexes or "")
    wanted = {_KIND_ALIASES.get(part.strip().lower()) for part in raw.split(",")}
    return [k for k in KINDS if k in wanted] or ["entity"]


def rrf_scores(*ranked_lists: list[dict], k: int = RRF_K, key: Callable[[dict], str | None] | None = None):
    """``(scores, first_hit_per_id)`` of reciprocal-rank fusion."""
    key = key or (lambda hit: hit.get("entity_id") or hit.get("id"))
    scores: dict[str, float] = {}
    keep: dict[str, dict] = {}
    for lst in ranked_lists:
        for rank, hit in enumerate(lst):
            hid = key(hit)
            if not hid:
                continue
            scores[hid] = scores.get(hid, 0.0) + 1.0 / (k + rank)
            keep.setdefault(hid, hit)
    return scores, keep


def rrf_fuse(*ranked_lists: list[dict], k: int = RRF_K, key: Callable[[dict], str | None] | None = None) -> list[dict]:
    """Reciprocal-rank fusion: score(id) = Σ 1/(k + rank), first-seen hit kept.

    A port of ``mcp/server.py::_rrf_fuse`` (:905-922), not an import: the API
    never imports the MCP server (mcp imports ``api.services``, never the
    reverse). ``test_search_service.py`` pins parity on the MCP test's
    fixture plus an ``id``-keyed hit, so Track R can make the MCP copy an
    import of this one.
    """
    scores, keep = rrf_scores(*ranked_lists, k=k, key=key)
    return [keep[h] for h in sorted(scores, key=lambda h: -scores[h])]


def _fuse(*key_lists: list[str]) -> tuple[list[str], dict[str, float]]:
    scores, _ = rrf_scores(*[[{"id": key} for key in keys] for keys in key_lists])
    return sorted(scores, key=lambda h: -scores[h]), scores


def _dedupe(keys: Iterable) -> list:
    seen: set = set()
    out = []
    for key in keys:
        if key and key not in seen:
            seen.add(key)
            out.append(key)
    return out


def quick_score(tokens: list[str], fields: Iterable[tuple[str, float, str]]) -> tuple[float, str]:
    """QuickMatch's score over the fields the server holds (design §1.2).

    Per token, the best of: the whole field equals the query (tier 0), the
    field starts with the token (1), a word in the field starts with it (2) —
    the tiers an FTS prefix match can witness. Initials and mid-word
    substrings (QuickMatch tiers 3–4) have no index behind them server-side
    (G136 R7); the app's local tier covers them. A token FTS matched that no
    short field shows was matched in the body, and is credited as a body
    word-start, (5 − 2) × 0.4. Returns the score and the label of the field
    that contributed most.
    """
    folded = [(text_fold.fold(t), w, label) for t, w, label in fields if t]
    whole = " ".join(tokens)
    total, best_pts, best_label = 0.0, -1.0, "body"
    for tok in tokens:
        pts, label = (_TIERS - 2) * 0.4, "body"
        for text, weight, flabel in folded:
            words = text_fold.words(text)
            if text == tok or " ".join(words) == whole:
                tier = 0
            elif text.startswith(tok):
                tier = 1
            elif any(w.startswith(tok) for w in words):
                tier = 2
            else:
                continue
            if (_TIERS - tier) * weight > pts:
                pts, label = (_TIERS - tier) * weight, flabel
        total += pts
        if pts > best_pts:
            best_pts, best_label = pts, label
    return total, best_label


def snippet_window(text: str | None, tokens: list[str], limit: int = SNIPPET_CHARS) -> tuple[str, list[list[int]]]:
    """A ≤ ``limit``-character window of ``text`` (whitespace collapsed)
    around the first match, ``…`` where it was cut, and the match offsets
    INTO THE SNIPPET — the exact string the row renders."""
    flat = " ".join((text or "").split())
    if not flat:
        return "", []
    spans = text_fold.match_offsets(flat, tokens)
    if len(flat) <= limit:
        return flat, spans
    first = spans[0][0] if spans else 0
    start = max(0, first - limit // 3)
    if start > 0:
        space = flat.find(" ", start)
        if 0 <= space < first:
            start = space + 1  # never open mid-word: a cut word would read as a word start
    end = min(len(flat), start + limit)
    if end < len(flat):
        cut = flat.rfind(" ", start, end)
        if cut > first:
            end = cut
    snippet = ("…" if start > 0 else "") + flat[start:end] + ("…" if end < len(flat) else "")
    return snippet, text_fold.match_offsets(snippet, tokens)


# --- per-request context ----------------------------------------------------------


@dataclass
class _Ctx:
    memory_path: Path
    reader: search_index.Reader | None
    q: str
    tokens: list[str]
    kinds: list[str]
    per_kind: int
    mode: str
    legs: dict[str, list[dict]] | None = None

    @property
    def match(self) -> str:
        return search_index.match_expression(self.tokens)

    @property
    def split_media(self) -> bool:
        return "media" in self.kinds

    @property
    def recent_first(self) -> bool:
        return self.mode == "prefix"


def _vector_legs(ctx: _Ctx, embed_fn) -> dict[str, list[dict]] | None:
    """The stored-vector legs, one embed for all of them; ``None`` when no
    vector index answers (then hybrid honestly reports ``mode: lexical``)."""
    want: dict[str, int] = {}
    if "entity" in ctx.kinds or "media" in ctx.kinds:
        want["entities"] = ctx.per_kind * 2
    if "claim" in ctx.kinds:
        want["claims"] = ctx.per_kind * 2
    if "episode" in ctx.kinds:
        want["episodes"] = ctx.per_kind * 2
    try:
        from api.services.vector_index import SqliteVecIndexer

        indexer = SqliteVecIndexer(ctx.memory_path, embed_fn=embed_fn) if embed_fn else SqliteVecIndexer(ctx.memory_path)
        legs = indexer.search_kinds(ctx.q, want)
    except Exception as exc:  # never the query text in a log (K9)
        logger.debug(f"search_service: vector legs unavailable ({type(exc).__name__})")
        return None
    return legs if any(legs.values()) else None


def _stem(row: dict) -> str:
    return Path(str((row.get("metadata") or {}).get("file_path") or "")).stem


def _belongs(is_media: bool, kind: str, split_media: bool) -> bool:
    """Which group a page lands in: media pages are their own group only
    when ``media`` was asked for; otherwise they are entities (the pre-G136
    ``/search`` returned every page as an entity, and ``kinds=entity`` keeps
    doing so). A page is reported once."""
    return is_media if kind == "media" else (not is_media or not split_media)


# --- pages: entities and media ------------------------------------------------------


@dataclass
class _Page:
    doc: search_index.Doc
    score: float
    label: str
    sort: tuple = ()
    reason: str | None = None  # the claim text, when reached through a claim


def _page_fields(meta: dict) -> list[tuple[str, float, str]]:
    return [
        (meta.get("name", ""), 1.0, "name"),
        *[(a, 0.9, "alias") for a in [*meta.get("aliases", []), *meta.get("authors", [])]],
        *[(t, 0.7, "keyword") for t in [*meta.get("tags", []), meta.get("site", ""), meta.get("channel", "")]],
    ]


def _page(doc: search_index.Doc, tokens: list[str], bm: float = 0.0) -> _Page:
    score, label = quick_score(tokens, _page_fields(doc.meta))
    meta = doc.meta
    return _Page(doc, score, label, (meta.get("status") == "archived", -score, bm, str(meta.get("name", "")).casefold()))


def _page_hit(page: _Page, tokens: list[str], score: float, snippet_src: str, kind: str) -> SearchHit:
    meta = page.doc.meta
    snippet, offsets = snippet_window(snippet_src, tokens)
    if meta.get("type") == "media":
        authors = meta.get("authors") or []
        subtitle = (", ".join(authors[:3]) + (" et al." if len(authors) > 3 else "")) if authors else (meta.get("site") or None)
    elif page.reason:
        subtitle = page.reason
    elif page.label == "alias":
        subtitle = next((a for a in meta.get("aliases", []) if text_fold.match_offsets(a, tokens)), None)
    else:
        subtitle = None
    return SearchHit(
        id=page.doc.ref,
        name=meta.get("name") or page.doc.ref,
        type=meta.get("type") or "concept",
        status=meta.get("status") or "active",
        confidence=float(meta.get("confidence") or 0.0),
        score=score,
        snippet=snippet,
        kind=kind,
        subtitle=subtitle,
        snippet_offsets=offsets,
        matched_field=page.label,
        origin=meta.get("origin") or None,
        timestamp=meta.get("saved_at") or None,
    )


def _lexical_pages(ctx: _Ctx, tables: list[str]) -> list[_Page]:
    """Entity or media pages, QuickMatch-ranked, archived last, dropped never
    (``dropped`` = user-dismissed, never resurfaced)."""
    rows: list[tuple[int, float]] = []
    for table in tables:
        rows += ctx.reader.ranked(table, ctx.match, ctx.per_kind * CANDIDATE_FACTOR)
    docs = ctx.reader.docs([d for d, _ in rows])
    pages = [_page(docs[d], ctx.tokens, bm) for d, bm in rows if d in docs and docs[d].meta.get("status") != "dropped"]
    pages.sort(key=lambda p: p.sort)
    return pages


def _pages_kind(ctx: _Ctx, kind: str, lexical: list[_Page], claims: list["_Claim"]) -> list[SearchHit]:
    vec: list[str] = []
    for row in (ctx.legs or {}).get("entities", []):
        meta = row.get("metadata") or {}
        if _belongs(meta.get("type") == "media", kind, ctx.split_media) and meta.get("status") != "dropped":
            vec.append(str(meta.get("entity_id") or ""))
    # The claim leg (R3 P2) is LEXICAL in both modes (G136 R9): current claims
    # whose words match, mapped to the page they are about. A vector leg
    # always returns k neighbours, so a semantic claim leg would give every
    # page with nearby claims a second always-present semantic vote on top of
    # the entity vectors — in a one-claim fixture it put that claim's subject
    # above the only true semantic match. Vector claims still rank the
    # `claim` group itself.
    via_claim: list[str] = []
    reasons: dict[str, str] = {}
    if kind == "entity":
        for c in claims:
            if c.hit.valid_to is None and c.hit.subject_id:
                via_claim.append(c.hit.subject_id)
                reasons.setdefault(c.hit.subject_id, c.hit.name)
        via_claim = _dedupe(via_claim)
    keys = [p.doc.ref for p in lexical]
    if ctx.legs is not None:
        order, scores = _fuse(keys, _dedupe(vec), via_claim)
    else:
        # Prefix mode keeps the exact-name hit on top: lexical order first,
        # pages reached only through one of their claims after it.
        order, scores = _dedupe([*keys, *via_claim]), {p.doc.ref: p.score for p in lexical}
    pages = {p.doc.ref: p for p in lexical}
    missing = [ref for ref in order[: ctx.per_kind * 2] if ref not in pages]
    if missing:
        allowed = tuple(k for k in ("entity", "media") if _belongs(k == "media", kind, ctx.split_media))
        for ref, doc in ctx.reader.docs_by_ref(allowed, missing).items():
            if doc.meta.get("status") != "dropped":
                label = "claim" if ref in reasons else "semantic"
                pages[ref] = _Page(doc, scores.get(ref, 0.0), label, reason=reasons.get(ref))
    # Archived pages rank below every live one in every mode — the fallback
    # tier `search_entities` already gives them (vector_index.py:345-373) —
    # and the tier is applied BEFORE the cut, so an archived neighbour never
    # displaces a live page from the group.
    ranked = [pages[ref] for ref in order if ref in pages]
    ranked.sort(key=lambda p: p.doc.meta.get("status") == "archived")
    chosen = ranked[: ctx.per_kind]
    bodies = {
        **ctx.reader.column("ent", "body", [p.doc.id for p in chosen if p.doc.kind == "entity"]),
        **ctx.reader.column("med", "body", [p.doc.id for p in chosen if p.doc.kind == "media"]),
    }
    hits = []
    for page in chosen:
        src = page.doc.meta.get("summary", "")
        body = bodies.get(page.doc.id, "")
        if not text_fold.match_offsets(src, ctx.tokens) and text_fold.match_offsets(body, ctx.tokens):
            src = body  # the snippet shows where the words are
        hits.append(_page_hit(page, ctx.tokens, scores.get(page.doc.ref, page.score), src, kind))
    return hits


# --- claims ---------------------------------------------------------------------------


@dataclass
class _Claim:
    hit: SearchHit
    sort: tuple = ()


def _claim_hit(subject: search_index.Doc, text: str, payload: dict, tokens: list[str], score: float, label: str) -> SearchHit:
    snippet, offsets = snippet_window(text, tokens)
    ev = payload.get("evidence") or {}
    is_span = ev.get("kind") not in (None, "reasoning") and int(ev.get("start", -1)) >= 0
    return SearchHit(
        id=str(payload.get("id") or ""),
        name=text,
        type=subject.meta.get("type") or "concept",
        status=subject.meta.get("status") or "active",
        confidence=float(payload.get("confidence") or 0.0),
        score=score,
        snippet=snippet,
        kind="claim",
        subtitle=subject.meta.get("name") or subject.ref,
        snippet_offsets=offsets,
        matched_field=label,
        subject_id=subject.ref,
        episode_id=(ev.get("episode") or None) if is_span else None,
        start=int(ev["start"]) if is_span else None,
        end=int(ev["end"]) if is_span else None,
        hash=(ev.get("hash") or None) if is_span else None,
        evidence_kind=ev.get("kind") or None,
        valid_from=payload.get("valid_from") or None,
        valid_to=payload.get("valid_to") or None,
        superseded_by=payload.get("superseded_by") or None,
    )


def _lexical_claims(ctx: _Ctx) -> list[_Claim]:
    """Current claims first, history after (R3 P4: a superseded claim is
    shown, as "was X until <date>", never hidden and never ranked above
    what is true now)."""
    rows = ctx.reader.claims(ctx.match, ctx.per_kind * CANDIDATE_FACTOR)
    subjects = ctx.reader.docs([doc_id for _, doc_id, *_ in rows])
    out: list[_Claim] = []
    for _rowid, doc_id, bm, text, payload in rows:
        subject = subjects.get(doc_id)
        if subject is None or not payload.get("id"):
            continue
        fields = [
            (text, 1.0, "name"),
            (subject.meta.get("name", ""), 0.9, "alias"),
            (f"{payload.get('predicate', '')} {payload.get('object', '')}", 0.7, "keyword"),
        ]
        score, label = quick_score(ctx.tokens, fields)
        out.append(_Claim(_claim_hit(subject, text, payload, ctx.tokens, score, label),
                          (payload.get("valid_to") is not None, -score, bm)))
    out.sort(key=lambda c: c.sort)
    return out


def _claim_order(ctx: _Ctx, lexical: list[_Claim]) -> tuple[list[str], dict[str, float]]:
    keys = [c.hit.id for c in lexical]
    if ctx.legs is None:
        return keys, {c.hit.id: c.hit.score for c in lexical}
    vec = [str((row.get("metadata") or {}).get("claim_id") or "") for row in ctx.legs.get("claims", [])]
    return _fuse(keys, _dedupe(vec))


def _claims_kind(ctx: _Ctx, lexical: list[_Claim], order: list[str], scores: dict[str, float]) -> list[SearchHit]:
    hits = {c.hit.id: c.hit for c in lexical}
    missing = [cid for cid in order[: ctx.per_kind] if cid not in hits]
    if missing:
        rows = ctx.reader.claims_by_id(missing)
        subjects = ctx.reader.docs([doc_id for doc_id, _t, _p in rows.values()])
        for cid, (doc_id, text, payload) in rows.items():
            if doc_id in subjects:
                hits[cid] = _claim_hit(subjects[doc_id], text, payload, ctx.tokens, 0.0, "semantic")
    ranked = [hits[cid] for cid in order if cid in hits]
    # History after every current claim in every mode (G136 R10), applied
    # BEFORE the cut: fusion alone ties a lexical-only superseded claim with
    # the first semantic neighbour, since vector claims are current-only.
    ranked.sort(key=lambda h: h.valid_to is not None)
    chosen = ranked[: ctx.per_kind]
    for hit in chosen:
        hit.score = scores.get(hit.id, hit.score)
    return chosen


# --- episodes ---------------------------------------------------------------------------


@dataclass
class _Episode:
    doc: search_index.Doc
    label: str
    passage: tuple[int, int, int] | None = None  # (rowid, start, end) of the best matching passage


def _lexical_episodes(ctx: _Ctx) -> list[_Episode]:
    """One row per episode: title matches first (the strongest field), then
    passage matches — newest-written first in prefix mode, bm25 in hybrid."""
    limit = ctx.per_kind * CANDIDATE_FACTOR
    heads = ctx.reader.ranked("epi", ctx.match, limit, recent_first=ctx.recent_first)
    passages = ctx.reader.passages(ctx.match, limit * 4, recent_first=ctx.recent_first)
    best: dict[int, tuple[int, int, int]] = {}
    for rowid, doc_id, s, e, _ in passages:
        best.setdefault(doc_id, (rowid, s, e))
    titled = {d for d, _ in heads}
    order = _dedupe([d for d, _ in heads] + [d for _, d, *_ in passages])[:limit]
    docs = ctx.reader.docs(order)
    return [_Episode(docs[d], "name" if d in titled else "body", best.get(d)) for d in order if d in docs]


def _line_span(text: str, s: int, e: int, tokens: list[str]) -> tuple[int, int]:
    """The line of passage ``text[s:e]`` holding the first match, as absolute
    offsets: a tighter highlight than the whole passage, and still a span
    whose ``text[start:end]`` contains the match (design §3.10)."""
    passage = text[s:e]
    spans = text_fold.match_offsets(passage, tokens)
    if not spans:
        return s, e
    at = spans[0][0]
    lo = passage.rfind("\n", 0, at) + 1
    hi = passage.find("\n", at)
    return s + lo, s + (hi if hi != -1 else len(passage))


def _locate_chunk(rows: list[tuple[int, int, int, str]], chunk: str) -> tuple[int, int] | None:
    """The passage holding a vector chunk, found EXACTLY: passages tile the
    body, so the body is their concatenation, and a chunk
    (``vector_index._chunk_episode_body``, a stripped slice of that body) is
    found with ``str.find`` — never fuzzy (G118 R5)."""
    head = (chunk or "").strip()[:200]
    if not head:
        return None
    at = "".join(t for *_, t in rows).find(head)
    if at == -1:
        return None
    return next(((s, e) for _r, s, e, _t in rows if s <= at < e), None)


def _episode_hit(ctx: _Ctx, ep: _Episode, score: float, chunk: str = "") -> SearchHit:
    meta = ep.doc.meta
    lo = ep.doc.id << search_index.ROW_BITS
    start = end = kind = None
    if ep.passage is not None:
        rowid, s, e = ep.passage
        # Passages tile the body from 0, so passages 1..rowid ARE body[:e].
        text = "".join(t for *_, t in ctx.reader.episode_passages(ep.doc.id, until=rowid))
        start, end = _line_span(text, s, e, ctx.tokens)
        src = text[start:end]
    else:
        rows = ctx.reader.episode_passages(ep.doc.id, until=None if chunk else lo | 1)
        text = "".join(t for *_, t in rows)
        span = _locate_chunk(rows, chunk) if chunk else None
        if span is not None:
            start, end = span
        src = text[start:end] if span is not None else text[: SNIPPET_CHARS * 2]
    if start is not None:
        kind = evidence.speaker_kind(text, start)
    snippet, offsets = snippet_window(src, ctx.tokens)
    return SearchHit(
        id=ep.doc.ref,
        name=meta.get("title") or "Untitled",
        type="episode",
        status="active",
        confidence=0.0,
        score=score,
        snippet=snippet,
        kind="episode",
        snippet_offsets=offsets,
        matched_field=ep.label,
        episode_id=ep.doc.ref,
        conversation_id=meta.get("conversation_id") or None,
        harness=meta.get("harness") or None,
        origin=meta.get("origin") or None,
        timestamp=meta.get("timestamp") or None,
        start=start,
        end=end,
        # A span without its hash could not be verified (G118 R2); a hit
        # with no span carries neither.
        hash=(meta.get("hash") or None) if start is not None else None,
        evidence_kind=kind,
    )


def _episodes_kind(ctx: _Ctx, lexical: list[_Episode]) -> list[SearchHit]:
    chunks: dict[str, str] = {}
    vec: list[str] = []
    for row in (ctx.legs or {}).get("episodes", []):
        stem = _stem(row)
        if stem:
            vec.append(stem)
            chunks.setdefault(stem, row.get("text") or "")
    keys = [ep.doc.ref for ep in lexical]
    if ctx.legs is not None:
        order, scores = _fuse(keys, _dedupe(vec))
    else:
        order, scores = keys, {ref: float(len(keys) - i) for i, ref in enumerate(keys)}
    eps = {ep.doc.ref: ep for ep in lexical}
    missing = [ref for ref in order[: ctx.per_kind] if ref not in eps]
    for ref, doc in ctx.reader.docs_by_ref(("episode",), missing).items():
        eps[ref] = _Episode(doc, "semantic")
    return [
        _episode_hit(ctx, eps[ref], scores.get(ref, 0.0), chunks.get(ref, "") if eps[ref].label == "semantic" else "")
        for ref in order[: ctx.per_kind]
        if ref in eps
    ]


# --- inbox ------------------------------------------------------------------------------


def _inbox_kind(ctx: _Ctx) -> tuple[list[SearchHit], int | None]:
    """Inbox questions, filtered exactly as ``GET /inbox`` filters them:
    a deferred item or one whose subject is gone is not served (G98)."""
    rows = ctx.reader.ranked("inb", ctx.match, INBOX_SCAN)
    docs = ctx.reader.docs([d for d, _ in rows])
    today = str(date.today())
    gone: dict[tuple[str, str], bool] = {}
    ranked: list[tuple[tuple, SearchHit]] = []
    for doc_id, bm in rows:
        doc = docs.get(doc_id)
        if doc is None:
            continue
        meta = doc.meta
        if inbox_questions.is_deferred({"remind_after": meta.get("remind_after")}, today):
            continue
        subject = (meta.get("entity_id") or "", meta.get("kind") or "")
        if subject not in gone:
            # A private helper, on purpose: the SAME test load_inbox applies,
            # so the palette can never offer a card /inbox hides (precedent:
            # sources.py reads link_enrichment's private extractor this way).
            gone[subject] = inbox_service._subject_gone(ctx.memory_path, *subject)
        if gone[subject]:
            continue
        fields = [(meta.get("question", ""), 1.0, "name"), (meta.get("entity_name", ""), 0.9, "alias"),
                  (meta.get("kind", ""), 0.7, "keyword")]
        score, label = quick_score(ctx.tokens, fields)
        snippet, offsets = snippet_window(meta.get("question", ""), ctx.tokens)
        hit = SearchHit(
            id=doc.ref, name=meta.get("question") or doc.ref, type=meta.get("kind") or "inbox",
            status=meta.get("status") or "pending", confidence=0.0, score=score, snippet=snippet,
            kind="inbox", subtitle=meta.get("entity_name") or None, snippet_offsets=offsets,
            matched_field=label, subject_id=meta.get("entity_id") or None,
        )
        ranked.append(((-score, -float(meta.get("priority") or 0.0), bm), hit))
    ranked.sort(key=lambda r: r[0])
    total = len(ranked) if len(rows) < INBOX_SCAN else None
    return [hit for _k, hit in ranked][: ctx.per_kind], total


# --- the two paths ------------------------------------------------------------------------


def _search_indexed(ctx: _Ctx) -> tuple[dict[str, list[SearchHit]], dict[str, int]]:
    out: dict[str, list[SearchHit]] = {}
    totals: dict[str, int] = {}
    tokens = bool(ctx.tokens)
    claims = _lexical_claims(ctx) if tokens and ("claim" in ctx.kinds or "entity" in ctx.kinds) else []
    if "entity" in ctx.kinds:
        tables = ["ent"] if ctx.split_media else ["ent", "med"]
        lexical = _lexical_pages(ctx, tables) if tokens else []
        out["entity"] = _pages_kind(ctx, "entity", lexical, claims)
        if tokens:
            totals["entity"] = sum(ctx.reader.count(t, ctx.match) for t in tables)
    if "claim" in ctx.kinds:
        order, scores = _claim_order(ctx, claims)
        out["claim"] = _claims_kind(ctx, claims, order, scores)
        if tokens:
            totals["claim"] = ctx.reader.count("clm", ctx.match)
    if "episode" in ctx.kinds:
        out["episode"] = _episodes_kind(ctx, _lexical_episodes(ctx) if tokens else [])
        if tokens:
            totals["episode"] = ctx.reader.count_episodes(ctx.match)
    if "media" in ctx.kinds:
        out["media"] = _pages_kind(ctx, "media", _lexical_pages(ctx, ["med"]) if tokens else [], [])
        if tokens:
            totals["media"] = ctx.reader.count("med", ctx.match)
    if "inbox" in ctx.kinds and tokens:
        out["inbox"], total = _inbox_kind(ctx)
        if total is not None:
            totals["inbox"] = total
    return out, totals


def _fm_meta(stem: str, fm: dict) -> dict:
    """The index's page meta, rebuilt from frontmatter (the fallback path)."""
    def strs(value):
        return [str(v).strip() for v in value if str(v or "").strip()] if isinstance(value, list) else []

    media = fm.get("media") if isinstance(fm.get("media"), dict) else {}
    paper = fm.get("paper") if isinstance(fm.get("paper"), dict) else {}
    return {
        "name": str(fm.get("name") or stem.replace("-", " ").title()),
        "type": str(fm.get("type", "concept") or "concept"),
        "status": str(fm.get("status", "active") or "active"),
        # The index's own tolerant reader: a hand-edited `confidence: high`
        # must not turn the fallback into a 500 (G136 R12).
        "confidence": search_index._float(fm.get("confidence")),
        "summary": "",
        "aliases": strs(fm.get("aliases"))[:8],
        "tags": strs(fm.get("tags"))[:8],
        "authors": strs(paper.get("authors"))[:6],
        "site": str(media.get("site") or ""),
        "channel": str(media.get("channel") or ""),
        "origin": str(fm.get("origin") or ""),
        "saved_at": str(fm.get("saved_at") or media.get("saved_at") or ""),
    }


def _search_fallback(ctx: _Ctx) -> tuple[dict[str, list[SearchHit]], dict[str, int]]:
    """No usable FTS index yet (building / unavailable): entity and media
    pages from ``bank_index``'s frontmatter cache — names, aliases, tags;
    never a body read and never a parse per request (R6 §4.2) — fused with
    the vector entity leg in hybrid. Claims, conversations and inbox need the
    index and come back empty; ``index_state`` says why."""
    out: dict[str, list[SearchHit]] = {k: [] for k in ctx.kinds}
    totals: dict[str, int] = {}
    docs: dict[str, search_index.Doc] = {}
    lexical: dict[str, list[_Page]] = {"entity": [], "media": []}
    for f in bank_index.files(ctx.memory_path, "entities"):
        meta = _fm_meta(f.stem, f.frontmatter or {})
        if meta["status"] == "dropped":
            continue
        doc = search_index.Doc(0, "media" if meta["type"] == "media" else "entity", f.stem, meta)
        docs[f.stem] = doc
        fields = _page_fields(meta)
        if ctx.tokens and all(any(w.startswith(t) for text, _w, _l in fields for w in text_fold.words(text)) for t in ctx.tokens):
            lexical["media" if ctx.split_media and doc.kind == "media" else "entity"].append(_page(doc, ctx.tokens))
    for kind in ("entity", "media"):
        if kind not in ctx.kinds:
            continue
        pages = sorted(lexical[kind], key=lambda p: p.sort)
        if ctx.tokens:
            totals[kind] = len(pages)
        order, scores = [p.doc.ref for p in pages], {p.doc.ref: p.score for p in pages}
        by_ref = {p.doc.ref: p for p in pages}
        if ctx.legs is not None:
            vec = [str((r.get("metadata") or {}).get("entity_id") or "") for r in ctx.legs.get("entities", [])]
            vec = [ref for ref in vec if ref in docs and _belongs(docs[ref].kind == "media", kind, ctx.split_media)]
            order, scores = _fuse(order, _dedupe(vec))
            for ref in order:
                if ref not in by_ref and ref in docs:
                    by_ref[ref] = _Page(docs[ref], scores.get(ref, 0.0), "semantic")
        chosen = [by_ref[ref] for ref in order if ref in by_ref][: ctx.per_kind]
        out[kind] = [_page_hit(p, ctx.tokens, scores.get(p.doc.ref, p.score), "", kind) for p in chosen]
    return out, totals


def search(
    memory_path: Path,
    q: str,
    *,
    kinds: Iterable[str] = ("entity",),
    mode: str = "hybrid",
    per_kind: int = 8,
    freshness_ttl_s: float | None = None,
    embed_fn=None,
) -> SearchResponse:
    """Search one bank. ``memory_path`` is the caller's ACTIVE bank (the
    router passes ``settings.memory_path``; MCP will pass its own resolved
    path) — this function never resolves a bank (the split-brain rule)."""
    wanted = set(kinds)
    ctx = _Ctx(
        memory_path=Path(memory_path),
        reader=None,
        q=q or "",
        tokens=text_fold.query_tokens(q),
        kinds=[k for k in KINDS if k in wanted] or ["entity"],
        per_kind=max(1, min(int(per_kind or 1), MAX_PER_KIND)),
        mode=mode if mode in MODES else "hybrid",
    )
    semantic = ctx.mode == "hybrid" and len(ctx.q.strip()) >= text_fold.MIN_TOKEN_CHARS
    if not ctx.tokens and not semantic:
        return SearchResponse(results=[], totals={}, mode=ctx.mode, index_state="ready")
    state = search_index.ensure_fresh(ctx.memory_path, max_age_s=freshness_ttl_s)
    if semantic:
        ctx.legs = _vector_legs(ctx, embed_fn)
    grouped = None
    if state in ("ready", "stale"):
        try:
            with search_index.Reader(ctx.memory_path) as reader:
                ctx.reader = reader
                grouped, totals = _search_indexed(ctx)
        except sqlite3.DatabaseError as exc:
            logger.warning(f"search_service: index read failed ({type(exc).__name__}); serving the fallback")
            search_index.invalidate(ctx.memory_path)
            state = "unavailable"
        finally:
            ctx.reader = None
    if grouped is None:
        grouped, totals = _search_fallback(ctx)
    ran = ctx.mode if ctx.mode == "prefix" or ctx.legs is not None else "lexical"
    results = [hit for kind in ctx.kinds for hit in grouped.get(kind, [])]
    return SearchResponse(results=results, totals=totals, mode=ran, index_state=state)


def lexical_entity_hits(memory_path: Path, query: str, top_k: int = 8) -> list[dict]:
    """The keyword leg ``mcp/server.py::handle_recall`` fuses (:953-956), in
    the shape its ``_rrf_fuse`` reads — alias-aware and token-level (R3 P1),
    where ``_keyword_search_entities`` (:1580-1608) is a whole-query
    substring that never reads aliases. Pure lexical: claim-reached rows are
    ``claim_subject_hits``' job. Adoption is Track R's (the G136 hand-off)."""
    resp = search(memory_path, query, kinds=("entity",), mode="prefix", per_kind=min(top_k, MAX_PER_KIND))
    return [{"entity_id": h.id, "source": "keyword", "score": h.score}
            for h in resp.results if h.matched_field != "claim"]


def claim_subject_hits(memory_path: Path, query: str, top_k: int = 8) -> list[dict]:
    """R3 P2's third recall leg: current claims matched lexically, mapped to
    the page they are about, deduplicated, best first."""
    resp = search(memory_path, query, kinds=("claim",), mode="prefix", per_kind=MAX_PER_KIND)
    subjects = _dedupe(h.subject_id for h in resp.results if not h.valid_to)
    return [{"entity_id": ref, "source": "claim", "score": 0.0} for ref in subjects][:top_k]
````

- [ ] **Step 6: Implement — the router.** Replace the whole of `api/routers/search.py` with:

````python
"""GET /search — find anything in memory: entities, beliefs, conversations,
sources and inbox questions (G136; round-3 design §3.9).

The work is ``search_service.search`` (lexical FTS5 + stored vectors, fused);
this router only parses parameters and moves that work OFF the event loop.
It used to be ``async def`` doing a blocking embed + KNN + a parse of every
entity file inline (R6 §4.2), so one slow search stalled every other request,
``/sync/events`` included. ``run_in_threadpool`` is the same move ``/ask``
made (``routers/ask.py``).

The pre-G136 call shape (``?q=&top_k=&indexes=entities``) stays valid and
returns entities only. No ETag: a per-keystroke query is never a Store
domain (K10), and the query is never logged (K9).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from starlette.concurrency import run_in_threadpool

from api.config import Settings, get_settings
from api.models.schemas import SearchResponse
from api.services import search_service

router = APIRouter()


@router.get("/search", response_model=SearchResponse)
async def search(
    q: str = Query(..., max_length=200),
    top_k: int = Query(8, ge=1, le=50),
    indexes: str | None = Query(None, max_length=200),
    kinds: str | None = Query(None, max_length=200),
    mode: str = Query("hybrid", pattern="^(prefix|hybrid)$"),
    per_kind: int | None = Query(None, ge=1, le=search_service.MAX_PER_KIND),
    settings: Settings = Depends(get_settings),
):
    return await run_in_threadpool(
        search_service.search,
        settings.memory_path,
        q,
        kinds=search_service.parse_kinds(kinds, indexes),
        mode=mode,
        per_kind=per_kind or min(top_k, search_service.MAX_PER_KIND),
    )
````

Then the access log (G136 R22). In `api/main.py`'s `# --- Logging setup ---` block, directly after
`logging.getLogger("openai").setLevel(logging.WARNING)` (before the `# Suppress litellm's print()
calls` comment), insert (`logging` is already imported there):

```python


# G136 / K9: the person's search words are never logged. uvicorn's access log
# writes every request line WITH its query string (to `logs/backend.*.log`
# under launchd, and both the plist and the app's spawn leave it on), and
# `/search?q=` fires on every keystroke of the palette; `/conversations/recent`
# carries a title filter the same way. Strip the query string of those paths
# at the logger, so the rail holds whatever flags uvicorn was started with.
# uvicorn configures its loggers before it imports this module, so the
# filter attached here is never replaced.
_QUERY_PATHS = frozenset({"/search", "/conversations/recent"})


class _RedactQueryString(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        # uvicorn's access record: (client, method, path?query, http_version, status)
        if isinstance(args, tuple) and len(args) == 5 and isinstance(args[2], str):
            path, sep, _query = args[2].partition("?")
            if sep and path in _QUERY_PATHS:
                record.args = (args[0], args[1], f"{path}?…", args[3], args[4])
        return True


logging.getLogger("uvicorn.access").addFilter(_RedactQueryString())
```

- [ ] **Step 7: Run, expect PASS.** Same command as Step 2 → 24 passed. Then the neighbours:
  `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_vector_index.py api/tests/test_vector_index_lock_handling.py api/tests/test_mcp_recall_fusion.py api/tests/test_ask_claim_retrieval.py -q -p no:cacheprovider`
  → green.

- [ ] **Step 8: Rails check.** `cd <worktree> && grep -n "logger\." api/services/search_service.py api/services/search_index.py api/routers/search.py`
  and `grep -n "search_kinds" api/services/vector_index.py` (both of its log messages name it). Read
  every hit: none may interpolate `q`, `ctx.q`, `query`, a token, a snippet or a hit's text, and the
  search path's failure logs name `type(exc).__name__`. The SQLite `OperationalError` message in
  `search_kinds` may stay: it names a table, and the query is a bound vector, never SQL text.

- [ ] **Step 9: Full suite.** → 0 failures, **2280 passed**.

- [ ] **Step 10: Commit.**

```bash
cd <worktree> && git add api/services/vector_index.py api/models/schemas.py api/services/search_service.py api/routers/search.py api/main.py api/tests/test_search_service.py && git commit -F - <<'EOF'
feat(search): /search off the event loop; kinds, totals, spans, prefix and hybrid (G136 S1/S2)

The router is a threadpool call over search_service. kinds = entity,
claim, episode, media, inbox (legacy indexes still honoured); totals are
exact lexical counts; hits carry kind, snippetOffsets, matchedField and
verifiable spans (the matching line, with the evidence hash). mode=prefix
is FTS only and never embeds; mode=hybrid fuses FTS with the stored
vectors by RRF, one embed per request (vector_index.search_kinds), with
current claims as a lexical third leg to their subject; history ranks
after every current claim in both modes. While the index builds,
entities come from the bank_index frontmatter cache. The query is never
logged: api/main.py strips it from uvicorn's access log for /search and
/conversations/recent (G136 R7-R16, R19, R22).

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 4: Sleep rebuilds it beside the vectors; launch and a bank switch warm it (R3)

**Files:**
- Modify: `api/services/sleep_cycle.py:1244-1251` (after the claims-index rebuild, before
  `if index_warnings:`)
- Modify: `api/main.py:40` (import), after `run_bank_migrations(settings.memory_path)` in `lifespan`
  (`:111` on the base; Task 3's access-log filter moves it about 25 lines down)
- Modify: `api/routers/banks.py:29` (import), `:104` (after the migrations in `activate_bank`)
- Test: `api/tests/test_sleep_search_index.py` (new)

**Interfaces:**
- Consumes `search_index.rebuild`, `search_index.warm_in_background`; the wired-cycle fakes of
  `api/tests/test_sleep_cycle_claims_wired.py` (`_seed_bank`, `_patch_boundaries`, `_settings`).

- [ ] **Step 1: Failing tests.** Create `api/tests/test_sleep_search_index.py`:

````python
"""G136 — the derived search index is rebuilt by Sleep beside the vector
index, warmed at launch and on a bank switch, and never fails a cycle.

Drives the REAL ``sleep_cycle.run`` through the boundaries
``test_sleep_cycle_claims_wired`` already fakes (no LLM, no embeddings, no
git) — imported rather than copied so the two wired tests can never drift.
"""
from __future__ import annotations

import asyncio

import pytest

from api.services import bank_index, bank_registry, search_index, sleep_cycle, text_fold
from test_sleep_cycle_claims_wired import _patch_boundaries, _seed_bank, _settings

EXTRACTED = [{
    "episode_id": "ep_2026-06-17_001",
    "episode_timestamp": "2026-06-17T10:00:00",
    "origin": "claude-code",
    "entities": [{"name": "Cicada", "type": "project", "source_episode": "ep_2026-06-17_001"}],
    "relationships": [],
}]
RESOLVED = [{
    "id": "cicada", "action": "create", "source_episode": "ep_2026-06-17_001",
    "source_episodes": ["ep_2026-06-17_001"], "trigger": "sleep/extraction",
    "entity": {"name": "Cicada", "type": "project", "confidence": 0.8, "key_facts": ["Built on sqlite-vec."]},
}]


@pytest.fixture(autouse=True)
def _fresh_state():
    bank_index.invalidate()
    search_index.reset()
    yield
    search_index.reset()
    bank_index.invalidate()


def _run(tmp_path, monkeypatch):
    memory = _seed_bank(tmp_path)
    _patch_boundaries(monkeypatch, memory, extracted=EXTRACTED, resolved_changes=RESOLVED, resolved_edges=[])
    asyncio.run(sleep_cycle.run(_settings(memory), cycle_id="2026-06-17_search"))
    return memory


def _refs(memory, table, q):
    with search_index.Reader(memory) as r:
        rows = r.ranked(table, search_index.match_expression(text_fold.query_tokens(q)), 10)
        return sorted(d.ref for d in r.docs([d for d, _ in rows]).values())


def test_a_sleep_cycle_leaves_the_search_index_fresh(tmp_path, monkeypatch):
    memory = _run(tmp_path, monkeypatch)
    assert (memory / search_index.DB_FILE).exists()
    # Read straight from the file — no ensure_fresh — so this proves Sleep
    # itself indexed the page it created, not a later request-time refresh.
    assert _refs(memory, "ent", "cicada") == ["cicada"]
    with search_index.Reader(memory) as r:
        assert r.count("pas", search_index.match_expression(["sqlite"])) == 1
    assert sleep_cycle._state.index_warning is None


def test_a_failed_search_index_rebuild_is_a_warning_not_a_failed_cycle(tmp_path, monkeypatch):
    def boom(_memory_path):
        raise RuntimeError("boom")

    monkeypatch.setattr(search_index, "rebuild", boom)
    memory = _run(tmp_path, monkeypatch)
    assert (memory / "entities" / "cicada.md").exists(), "the cycle still wrote memory"
    assert sleep_cycle._state.error is None
    assert "search index rebuild failed: RuntimeError: boom" in (sleep_cycle._state.index_warning or "")


def test_warm_in_background_builds_and_never_raises(tmp_path):
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    search_index.warm_in_background(memory)
    assert search_index.wait_idle(memory, timeout=10)
    assert search_index.ensure_fresh(memory) == "ready"
    search_index.warm_in_background(tmp_path / "not-a-bank")  # no thread, no file, no raise
    assert not (tmp_path / "not-a-bank").exists()


def test_activating_a_bank_warms_its_search_index(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from api import config, main

    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path))
    config.get_settings.cache_clear()
    bank_registry.scaffold_bank(tmp_path, git_init=False)
    client = TestClient(main.app)
    assert client.post("/banks", json={"name": "Research"}).status_code in (200, 201)
    bank = tmp_path / "banks" / "research"
    assert client.post("/banks/research/activate").status_code == 200
    assert search_index.wait_idle(bank, timeout=10)
    assert (bank / search_index.DB_FILE).exists()
    config.get_settings.cache_clear()
````

- [ ] **Step 2: Run, expect FAIL.**
  `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_sleep_search_index.py -q -p no:cacheprovider`
  → `test_a_sleep_cycle_leaves_the_search_index_fresh` fails (no `search_index.db` after the cycle),
  `test_a_failed_search_index_rebuild_is_a_warning_not_a_failed_cycle` fails (no warning — `rebuild`
  is never called), `test_activating_a_bank_warms_its_search_index` fails (no file after activate);
  `test_warm_in_background_builds_and_never_raises` already passes (Task 2 built it).

- [ ] **Step 3: Implement — Sleep.** In `api/services/sleep_cycle.py`, directly after the claims-index
  `try/except` (the one ending `index_warnings.append(warning)` inside `if indexer is not None:`) and
  before `if index_warnings:`, insert at the function's indentation (`asyncio` is already imported at
  `:1`):

```python
    # G136: the lexical index, rebuilt in full beside the vectors (round-3
    # spec decision 7) — independent of the vector indexer, so a missing
    # embedding model never leaves search's FTS half stale. Off the event
    # loop: 3–6 s of CPU at 2,000 entities / 1,500 episodes, while /search
    # keeps answering from the previous snapshot (WAL). Same contract as the
    # vector rebuilds: a failure is a warning on a cycle that still commits.
    try:
        from api.services import search_index

        await asyncio.to_thread(search_index.rebuild, memory_path)
    except Exception as e:
        warning = f"search index rebuild failed: {type(e).__name__}: {e}"
        logger.warning(warning)
        index_warnings.append(warning)

```

- [ ] **Step 4: Implement — launch and bank switch.** In `api/main.py` change
  `from api.services import bank_registry, sleep_scheduler` to
  `from api.services import bank_registry, search_index, sleep_scheduler`, and directly after
  `run_bank_migrations(settings.memory_path)` in `lifespan` add:

```python

    # G136: build or catch up the derived search index in the background, so
    # the first keystroke after launch finds it warm. Never blocks startup,
    # never raises (a cold build takes a few seconds; until it lands, /search
    # serves the frontmatter fallback and says `indexState: building`).
    search_index.warm_in_background(settings.memory_path)
```

In `api/routers/banks.py` change `from api.services import bank_index, bank_registry, sync_service`
to `from api.services import bank_index, bank_registry, search_index, sync_service`, and in
`activate_bank`, directly after
`await run_in_threadpool(run_bank_migrations, bank_registry.bank_dir(settings.memory_root, name))`,
add:

```python
    # G136: warm the newly active bank's search index off the request — the
    # switch returns at once; /search serves the fallback until it lands.
    search_index.warm_in_background(bank_registry.bank_dir(settings.memory_root, name))
```

- [ ] **Step 5: Run, expect PASS.** Same command as Step 2 → 4 passed. Then the wired Sleep tests and
  the lifespan tests:
  `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_sleep_cycle_claims_wired.py api/tests/test_sleep_control.py api/tests/test_sleep_resumable.py api/tests/test_sleep_connector_poll.py api/tests/test_banks.py api/tests/test_sync.py api/tests/test_auth.py api/tests/test_healthz_memory_root.py -q -p no:cacheprovider`
  → green.

- [ ] **Step 6: Full suite.** → 0 failures, **2284 passed**.

- [ ] **Step 7: Commit.**

```bash
cd <worktree> && git add api/services/sleep_cycle.py api/main.py api/routers/banks.py api/tests/test_sleep_search_index.py && git commit -F - <<'EOF'
feat(search): Sleep rebuilds the lexical index; launch and a bank switch warm it (G136)

Sleep rebuilds search_index.db beside the vector index, off the event
loop; a failure is an index warning on a cycle that still commits. The
lifespan and POST /banks/{name}/activate warm it in a background thread
so the first keystroke finds it built (G136 R3).

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 5: The latency budget, measured at the live bank's scale (R18)

A budget, not a behaviour: this test is expected to pass on its first run. If it fails, the regression
is in Tasks 2–3 — profile `search_service.search` on the fixture and fix it there before committing;
never raise the budget.

**Files:**
- Test: `api/tests/test_search_latency.py` (new)

- [ ] **Step 1: Write the test.** Create `api/tests/test_search_latency.py`:

````python
"""G136 — the search latency budget, measured at the live bank's scale.

A synthetic bank of 2,000 entities (3 claims each, prose from a paragraph
to ~8,000 characters) and 1,500 episodes (~11 MB of conversation text) — the live bank is 1,866 / 1,396 (TODO.md,
Live environment) — generated in the test's tmp dir from a fixed seed and a
made-up syllable vocabulary (no real names, no dictionary file, the same
numbers on every machine).

Budgets are the design's (round-3 §3.2): Pass A, ``mode=prefix``, p95
≤ 50 ms; Pass B, ``mode=hybrid``, 200 ms (G58's target). Measured on the
server twin — ``search_service.search``, the function ``GET /search`` runs
in its threadpool — so HTTP overhead is not in the number and a regression
in the search path is. Run with ``-s`` to see the numbers.
"""
from __future__ import annotations

import random
import statistics
import time
import zlib

import numpy as np
import pytest

from api.services import bank_index, markdown_parser, search_index, search_service

N_ENTITIES = 2000
N_EPISODES = 1500
N_QUERIES = 120
PALETTE_KINDS = ("entity", "claim", "episode", "media")
_SYLLABLES = ["ka", "lo", "mi", "ra", "tu", "sen", "vel", "dor", "qui", "zan",
              "pe", "ri", "mo", "na", "tho", "gar", "lin", "bex", "sol", "fen"]


def _word(rng: random.Random) -> str:
    return "".join(rng.choice(_SYLLABLES) for _ in range(rng.randint(2, 4)))


def _sentence(rng: random.Random, n: int) -> str:
    return " ".join(_word(rng) for _ in range(n)).capitalize() + "."


def _fake_embed(texts, *, is_query=False):
    """Hashed bag of words, 16 dims — deterministic and fast, so the hybrid
    number measures fusion and hydration, not a model."""
    rows = np.zeros((len(texts), 16), dtype=np.float32)
    for i, text in enumerate(texts):
        for word in text.lower().split()[:200]:
            rows[i, zlib.crc32(word.encode()) % 16] += 1.0
        rows[i, 0] += 0.01
    return rows / np.linalg.norm(rows, axis=1, keepdims=True)


@pytest.fixture(scope="module")
def big_bank(tmp_path_factory):
    rng = random.Random(7)
    memory = tmp_path_factory.mktemp("latency") / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True)
    vocab: list[str] = []
    types = ["project", "person", "concept", "tool", "media"]
    for i in range(N_ENTITIES):
        a, b = _word(rng), _word(rng)
        vocab += [a, b]
        claims = "".join(
            f"- id: clm_{i}_{k}\n  text: \"{_sentence(rng, 8)}\"\n  subject: e-{i}\n"
            f"  predicate: uses\n  object: {_word(rng)}\n"
            for k in range(3)
        )
        # Page prose from a paragraph to a long page (~8,000 characters, the
        # indexed cap), so snippet and highlight work is measured at its worst.
        prose = " ".join(_sentence(rng, 12) for _ in range(rng.choice([6, 6, 12, 40, 80])))
        body = f"## Summary\n{prose}\n\n```claims\n{claims}```\n"
        markdown_parser.write(memory / "entities" / f"e-{i}.md",
                              {"name": f"{a} {b} {i}", "type": types[i % 5], "status": "active",
                               "confidence": 0.5, "aliases": [_word(rng), _word(rng)], "tags": [_word(rng)]},
                              body)
    for i in range(N_EPISODES):
        turns = rng.choice([4, 8, 8, 12, 20, 60])
        body = "\n".join(f"{rng.choice(['user', 'assistant'])}: {_sentence(rng, rng.randint(10, 60))}"
                         for _ in range(turns))
        markdown_parser.write(memory / "episodes" / f"ep_2026-09-{i % 28 + 1:02d}_{i:03d}.md",
                              {"id": f"ep_{i}", "title": _sentence(rng, 4), "harness": "claude-code",
                               "session_id": f"ses_2026-09-01_{i:08d}", "timestamp": "2026-09-01T00:00:00+00:00"},
                              body)
    bank_index.invalidate()
    search_index.reset()
    started = time.perf_counter()
    search_index.rebuild(memory)
    build_s = time.perf_counter() - started
    queries = []
    for _ in range(N_QUERIES):
        word = rng.choice(vocab)
        queries.append(word[: rng.randint(2, min(7, len(word)))])
    queries += [f"{rng.choice(vocab)} {rng.choice(vocab)[:3]}" for _ in range(N_QUERIES // 4)]
    print(f"\nG136 synthetic bank: {N_ENTITIES} entities, {N_EPISODES} episodes; full index build {build_s:.2f} s")
    yield memory, queries
    search_index.reset()
    bank_index.invalidate()


def _measure(memory, queries, **kw) -> tuple[float, float]:
    for q in queries[:10]:  # warm the bank_index cache and SQLite's page cache
        search_service.search(memory, q, **kw)
    samples = []
    for q in queries:
        started = time.perf_counter()
        search_service.search(memory, q, **kw)
        samples.append(time.perf_counter() - started)
    return statistics.median(samples), statistics.quantiles(samples, n=20)[18]


def test_prefix_mode_p95_is_within_the_50ms_budget(big_bank):
    memory, queries = big_bank
    p50, p95 = _measure(memory, queries, kinds=PALETTE_KINDS, mode="prefix", per_kind=5)
    print(f"G136 prefix (palette Pass A, default freshness TTL): p50 {p50 * 1000:.1f} ms, p95 {p95 * 1000:.1f} ms")
    assert p95 <= 0.050


def test_prefix_mode_stays_within_budget_with_a_staleness_scan_on_every_request(big_bank):
    memory, queries = big_bank
    p50, p95 = _measure(memory, queries, kinds=PALETTE_KINDS, mode="prefix", per_kind=5, freshness_ttl_s=0)
    print(f"G136 prefix (scan on every request): p50 {p50 * 1000:.1f} ms, p95 {p95 * 1000:.1f} ms")
    assert p95 <= 0.050


def test_hybrid_mode_p95_is_within_the_200ms_budget(big_bank):
    from api.services.vector_index import SqliteVecIndexer

    memory, queries = big_bank
    indexer = SqliteVecIndexer(memory, embed_fn=_fake_embed)
    indexer.index_entities()
    indexer.index_claims()
    indexer.index_episodes()
    p50, p95 = _measure(memory, queries, kinds=PALETTE_KINDS, mode="hybrid", per_kind=5, embed_fn=_fake_embed)
    print(f"G136 hybrid (palette Pass B, fake embedder): p50 {p50 * 1000:.1f} ms, p95 {p95 * 1000:.1f} ms")
    assert p95 <= 0.200
````

- [ ] **Step 2: Run it with output.**
  `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_search_latency.py -q -s -p no:cacheprovider`
  → 3 passed in ~15–20 s, printing four lines that start `G136`. Keep them — Task 6 quotes them and the
  PR body must too. (Planning run: build 5.52 s; prefix p50 5.9 / p95 12.1 ms; prefix with a scan per
  request p50 16.0 / p95 21.8 ms; hybrid p50 14.6 / p95 36.3 ms. Critic's run with the fixes: build
  5.55 s; prefix p50 5.7 / p95 11.7 ms; with a scan p50 15.4 / p95 22.0 ms; hybrid p50 14.9 / p95
  40.5 ms.)

- [ ] **Step 3: Full suite.** → 0 failures, **2287 passed**.

- [ ] **Step 4: Commit.**

```bash
cd <worktree> && git add api/tests/test_search_latency.py && git commit -F - <<'EOF'
test(search): the G136 latency budget at the live bank's scale

2,000 entities and 1,500 episodes generated from a fixed seed and made-up
syllables. Asserts mode=prefix p95 <= 50 ms (with and without a
staleness scan on every request) and mode=hybrid p95 <= 200 ms with a
fake embedder, measured on search_service.search, the function the
router runs (G136 R18).

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 6: Docs — the row, the storage rail, the handoff

Placeholders only: no bank contents, no names or titles from a bank, no numbers read from a real bank.
Every number below comes from the synthetic fixture. Where Task 5 Step 2 printed different values on
this machine, use those.

**Files:**
- Modify: `docs/goals/memory-evolution.md` (new row after the `| G132 |` row, `:694`)
- Modify: `CLAUDE.md` (Storage Layer after `### sqlite-vec (vector index)`, `:323-327`; API traps
  `:561-562`; Key Design Decisions table after the sqlite-vec row, `:674`)
- Modify: `docs/goals/TODO.md` (after the round-2 baselines paragraph `:39-40`; "Pick up here" `:148`;
  the `## ✅ Shipped` list)

- [ ] **Step 1: `memory-evolution.md`.** Insert this row directly after the `| G132 |` row (if rows
  G133–G135 have landed from other round-3 tracks by merge time, keep numeric order — the conflict
  resolution is the union):

```markdown
| G136 | **Fast search everywhere — a derived full-text index and a find palette** (Rodrigo 2026-09-23: "quick retrieval fast search bars") | **Why.** ⌘K was Ask only, the graph's ⌘F matched names in the loaded snapshot, and nothing searched claims, conversation text, papers or the inbox. The server's `GET /search` blocked the event loop, ignored `indexes`, re-parsed every entity file per request on its fallback, and matched the whole query as one substring that never read aliases (R6 §4.2, R3 P1); superseded claims were unsearchable anywhere (R3 P4). Round-3 spec decision 7 settles the shape: a derived FTS5 index beside the vector index, and ⌘K becomes a *find* palette with Ask as a mode. **Server half shipped (2026-09-23, `feat/search-everywhere`, PR #TBD; plan `../superpowers/plans/2026-09-23-search-backend.md`, rulings G136 R1–R22):** `search_index.db` per bank, beside `vector_index.db` and never inside it — names + aliases + prose, every claim with superseded ones as history, episode titles + 600-character passages that tile the evidence text exactly, media/paper metadata, inbox questions; six per-kind FTS5 tables (`unicode61 remove_diacritics 2`, prefix `2 3 4`). Derived and disposable under TODO ruling 3 (a missing, corrupt or schema-mismatched file is rebuilt, never an error), excluded from git through `.git/info/exclude` before it first exists (a worktree or submodule bank's `.git` file is followed to the real git dir), rebuilt by Sleep beside the vectors and freshened per request from `bank_index` stamps (inline up to 64 changed files, a background worker beyond). `/search` runs in the threadpool, honours `kinds` (`entity, claim, episode, media, inbox`), returns exact lexical `totals`, verifiable spans (the matching line plus the evidence hash), `snippetOffsets` and `matchedField`; `mode=prefix` is FTS only and never embeds, `mode=hybrid` fuses it with the stored vectors by RRF with one embed, current claims as a lexical third leg to their subject (R3 P2); superseded claims rank after every current one; `dropped` pages are never indexed. `/conversations/recent?q=` filters titles before the cap. The query is never logged, uvicorn's access log included (`api/main.py` strips the query string of both paths). Measured on a synthetic 2,000-entity / 1,500-episode bank: prefix p50 5.9 ms / p95 12.1 ms (21.8 ms p95 with a staleness scan on every request), hybrid p95 36 ms with a fake embedder, full build 5.5 s. `search_service.lexical_entity_hits` / `claim_subject_hits` / `rrf_fuse` are ready for MCP recall (Track R). **Open:** the palette (design §6 S3–S6 — `QuickMatch`, the local tier, the ⌘K find overlay, the server tier and merge rule, in-page search fields, `GraphNode.aliases` after a payload measurement), MCP recall adoption, `GET /episodes/{id}/citations` (Track P, P4, over `Reader.claims_citing`). → extends **G93** (the search half of search/ask; cross-stream retrieval stays G93's), **G123** (the palette's local tier generalises its ranker), **G118** (every hit is a span a viewer can open). | 🛠️ server half shipped; palette next |
```

- [ ] **Step 2: `CLAUDE.md` — the storage rail.** Directly after the `### sqlite-vec (vector index)`
  paragraph (it ends "markdown, safe to delete at any time.") and before `### Telemetry ledger`,
  insert:

```markdown
### SQLite FTS5 (lexical index, G136)
`api/services/search_index.py`. One `search_index.db` per bank, **beside `vector_index.db` and never
inside it**: entity names + aliases + prose, every claim (superseded ones kept as history), episode
titles + 600-character passages that tile the evidence text exactly, media/paper metadata and inbox
questions, in six per-kind FTS5 tables (`unicode61 remove_diacritics 2`, prefix `2 3 4`; rowid
`doc_id << 16 | n`). `dropped` pages are never indexed. **Derived and disposable** (TODO ruling 3):
deleting it costs a few seconds of CPU and never a fact; a missing, corrupt or schema-mismatched file is
rebuilt, never an error. **Never tracked:** `bank_registry.ensure_derived_excluded` writes
`.git/info/exclude` before the file first exists. It follows a worktree or submodule bank's `.git` file
to the real git dir, and a new bank's `.gitignore` lists the file too. It never edits an existing
`.gitignore`, which would dirty the tree and smear into the next `git add -A` commit. **Freshness:**
Sleep rebuilds it beside the vectors; every read path calls `ensure_fresh`, a `bank_index` stamp diff
(at most one check a second, inline up to 64 changed files, one background worker beyond); the
lifespan and a bank switch warm it in the background. The caller always passes the active bank's path
— the module never resolves a bank (the split-brain rule). `search_service` ranks over it (QuickMatch
tiers 0–2), fuses it with the stored vectors in `mode=hybrid`, and **never embeds in `mode=prefix`**.
**The query is never logged**: not by loguru, and not by uvicorn's access log (`api/main.py` strips the
query string of `/search` and `/conversations/recent`, G136 R22).
```

- [ ] **Step 3: `CLAUDE.md` — API traps.** Replace the whole `/conversations/recent` bullet (both lines)

```markdown
- `GET /conversations/recent` is **CAPPED** (limit ≤ 200) and is never a membership test; filters
  apply BEFORE the cap. Use `GET /conversations/{id}` to resolve one id against the whole bank.
```

with

```markdown
- `GET /conversations/recent` is **CAPPED** (limit ≤ 200) and is never a membership test; filters
  (`harness`, `origin`, and `q`, a title filter) apply BEFORE the cap. Use `GET /conversations/{id}` to
  resolve one id against the whole bank.
- `GET /search` runs in the threadpool. `mode=prefix` (the per-keystroke pass) is FTS only and never
  loads the embedding model; `mode=hybrid` (the default) fuses FTS with the stored vectors and reports
  `mode: lexical` when no vector index answered. `totals` are exact **lexical** counts — semantic
  neighbours are ranked, never counted. An `indexState` other than `ready`/`stale` means entities and
  media only, from the frontmatter cache. No ETag: it is never a Store domain. Its query string (and
  `/conversations/recent`'s) is stripped from uvicorn's access log; a new query-bearing GET joins
  `_QUERY_PATHS` in `api/main.py`.
```


- [ ] **Step 4: `CLAUDE.md` — Key Design Decisions.** After the `| sqlite-vec over LEANN/FAISS | … |`
  row, add:

```markdown
| FTS5 beside sqlite-vec | Type-as-you-go needs words, not meanings: a derived lexical index answers a prefix in ~12 ms p95 at 2k entities / 1.5k episodes without an embedding call, and finds aliases, claims and conversation text by what they say. Derived and disposable, like the vectors. |
```

- [ ] **Step 5: `TODO.md`.** After the round-2 baselines paragraph (`**Test baselines after round 2:** …`),
  add:

```markdown
**Round 3, Track S-back — G136 server half (2026-09-23, `feat/search-everywhere`, PR #TBD).** `/search`
moved into the threadpool with `kinds`, exact lexical `totals`, spans and `mode=prefix|hybrid` over a
derived FTS5 index beside the vector index (`search_index.db`: excluded through `.git/info/exclude`,
rebuilt by Sleep, freshened per request from `bank_index` stamps), plus `/conversations/recent?q=`.
Backend **2287 passed** on the branch. The palette (design §6 S3–S6) starts after the Meadow foundation
(M1) merges; MCP recall adoption is Track R's — see the plan's hand-off.
```

In `## Pick up here`, after the paragraph that begins "The queue there, in order:", add:

```markdown
**Search (G136):** the server half has shipped. Next is the ⌘K find palette (design §6 S3–S6), after
M1; it builds against "The wire" in `docs/superpowers/plans/2026-09-23-search-backend.md`.
```

In `## ✅ Shipped`, after the `**Memory model** — …` paragraph, add:

```markdown
**Search** — **G136 server half (2026-09-23)** — the derived FTS5 index beside the vector index, `/search`
with kinds / lexical totals / spans / prefix and hybrid, `/conversations/recent?q=`; the palette is open
```

- [ ] **Step 6: Privacy read.** `cd <worktree> && git diff -- docs/goals CLAUDE.md` — read every added
  line: no person, company, title, URL or number from a bank; only placeholders and synthetic numbers.

- [ ] **Step 7: Commit.**

```bash
cd <worktree> && git add docs/goals/memory-evolution.md docs/goals/TODO.md CLAUDE.md && git commit -F - <<'EOF'
docs: G136 search everywhere, server half — the row, the FTS rail, the handoff

G136 filed and marked server-half shipped (the palette is next).
CLAUDE.md gains the FTS5 index as a derived, disposable artifact beside
sqlite-vec, the /search and ?q= traps, and a design-decision row.
TODO.md records the track, its baseline and what picks up next.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
```

---

## Not in scope

Named so a reviewer reads an absence as a decision, not an oversight.

- **Any Swift** — `QuickMatch`, `QuickIndex`, the ⌘K palette overlay and its menu commands,
  `CicadaSearchField`, the in-page fields (design §6 S3–S5). The palette track starts after M1.
- **`GraphNode.aliases` on `/graph`** (S6) — the design requires a payload measurement first.
- **MCP recall changes.** `mcp/server.py` is not edited (Track R is moving its tool bodies); adoption
  is in the hand-off below.
- **The `GET /episodes/{id}/citations` endpoint** (Track P, P4). The read it needs ships here (R20).
- **Typo tolerance** (R3 P1's `difflib` name match). QuickMatch has no typo tier either; where a fuzzy
  row would rank is a design question for the palette, not a server default.
- **R3 P4(a)–(c):** the vector claims index's dead `include_superseded`, `get_perspective` history, and
  "changed recently" lines in recall. History is searchable here; how recall surfaces it is Track Q's.
- **Re-chunking the vector index.** `_chunk_episode_body` keeps its stripped 4,000-character chunks;
  spans come from the FTS rows, the design's preferred option (§3.9 item 2).
- **Search telemetry of any kind.** Opening a palette result emits the existing G124 `read` event —
  the palette's, ids only. The server records nothing about a query.
- **An ETag or a Store domain for `/search`** (R19).
- **Date-scoped or filtered search** (G99 (i), G93's temporal scoping).
- **An LLM anywhere in search.**

---

## Hand-off

1. **Track R (MCP tool bodies move to `api/services/mcp_tools.py`, R-R2).** (a) `handle_recall`'s
   keyword leg (`mcp/server.py:953-956`, `_keyword_search_entities` at `:1580-1608`) becomes
   `search_service.lexical_entity_hits(memory_path, query, top_k=8)` — the same
   `{"entity_id", "source", "score"}` shape, alias-aware and token-level. (b) Add
   `search_service.claim_subject_hits(memory_path, query, top_k=8)` as a third `_rrf_fuse` list — R3
   P2's claim leg. (c) Replace `_rrf_fuse` with `from api.services.search_service import rrf_fuse`;
   `test_search_service.py::test_rrf_fuse_matches_the_mcp_helper_exactly` then compares the function
   with itself and can go. (d) The MCP process passes its own resolved bank path; the index file, its
   git exclusion and its freshness then work there too. Two processes refreshing one file never
   duplicate rows (delete by `doc_key` inside the transaction), though each keeps its own stamp cache.
   `test_mcp_recall_fusion.py` must stay green.
2. **The palette track (S3–S6)** builds against "The wire". Pass A =
   `kinds=entity,claim,episode,media&mode=prefix&per_kind=5`; Pass B = the same with `mode=hybrid`.
   `indexState: building|unavailable` means claims, conversations and inbox are empty on purpose — hide
   those groups, as §3.6 already does for an old backend; a missing `totals[kind]` renders "More…".
   Dedupe server rows against local ones by `(kind, id)`.
3. **Track P (P4 `GET /episodes/{id}/citations`).** `search_index.ensure_fresh(memory_path)`, then
   `with search_index.Reader(memory_path) as r: r.claims_citing(episode_id)` → `(doc_id, text,
   payload, span)`, with the subject from `r.docs([doc_id])`. The cold fallback (`partial: true`, §4.8
   item 3) is P4's.
4. **Track F (papers).** The index reads `paper: {authors, arxiv_id, doi}` (R7 §4's shape) on
   `type: media` pages. If Track F lands different keys, change `search_index._index_entity`'s media
   branch and `search_service._fm_meta` together and bump `search_index.SCHEMA_VERSION` — a bump
   rebuilds every bank's file on its next use.

---

## Verification the orchestrator runs at the end

1. `cd <worktree> && api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider` → **0 failures**,
   ≥ 2287 passed (2225 + 62). If the order-dependent `test_agent_provenance` case is the only red,
   re-run it alone and report both results.
2. `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_search_latency.py -q -s -p no:cacheprovider`
   → 3 passed; copy the four `G136 …` lines into the PR body.
3. `cd <worktree> && git diff --stat dev -- mcp/ app/` → empty (no MCP edit, no Swift).
4. `cd <worktree> && grep -n "logger\." api/services/search_service.py api/services/search_index.py api/services/text_fold.py api/routers/search.py`
   plus the two in `vector_index.search_kinds` — read every message; none interpolates the query, a
   token, a snippet or a hit's text. `grep -n "_QUERY_PATHS" api/main.py` → the filter is attached.
5. Break the budget on purpose once: add `time.sleep(0.06)` as the first statement of
   `search_service.search` (and `import time` at the top), run step 2 → both prefix tests FAIL; revert
   and re-run → green. A budget that has never failed is not known to work.
6. Live, after merge and a backend restart (`launchctl kickstart -k gui/$(id -u)/com.cicada.backend`),
   on the **demo** bank (`POST /banks/demo`, then activate it): (a)
   `curl -s -H "Authorization: Bearer $(cat ~/.cicada/api_token)" 'http://localhost:8000/search?q=al&kinds=entity,claim,episode,media&mode=prefix&per_kind=5'`
   → `indexState: ready` within a few seconds of the switch, grouped rows, `totals`; with
   `-o /dev/null -w '%{time_total}\n'` a few times → under 0.05 s once warm. (b) The same with
   `mode=hybrid` → `mode: hybrid` (the first call may load the embedder). (c) In that bank's directory:
   `git status --porcelain` empty and `git check-ignore -q search_index.db` exits 0. (d) Delete
   `search_index.db` and query again → 200 with `indexState: building`, then `ready` within seconds.
   (e) `GET /conversations/recent?limit=1&q=<a word from one demo conversation title>` returns it.
   (f) `grep -c "zebracorn" <repo>/logs/backend.out.log` after a
   `curl … '/search?q=zebracorn&mode=prefix'` → `0`, and the newest `GET /search` line in that file
   reads `/search?…`. Then, on the active real bank, only (c). The orchestrator measures; nothing from
   the bank goes into a doc.
7. **PR body states:** no Swift and `mcp/server.py` untouched; no ETag added or changed (the
   `/conversations/recent` recipe is byte-identical without `q`); no telemetry added and the query never
   logged (loguru or uvicorn's access log); the latency numbers from step 2; the hand-off to Tracks R,
   P and F.
