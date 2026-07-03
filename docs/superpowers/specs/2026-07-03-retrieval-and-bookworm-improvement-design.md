# Design: Cicada retrieval + Bookworm quality improvement

**Date:** 2026-07-03 · **Branch:** `feat/memory-evolution` · **Author:** Rodrigo + Claude
**Goal:** materially raise memory-retrieval accuracy for both small and large models answering
questions through the Bookworm MCP, and self-heal the consolidation defects that block retrieval.

---

## 1. Motivation & measured baseline

A 2026-07-03 audit scored a 14-question retrieval benchmark (haiku + sonnet answering through the
MCP). The first run scored 0.39 / 0.45 — but it measured a **broken MCP** that served the stale
legacy root bank with no vector index (the "split-brain" bug, since fixed: `mcp/server.py`
`get_memory_path()` now resolves the active bank via `bank_registry.resolve_active_bank_path`).

**Re-measured true baseline (fixed, bank-aware MCP, active bank `claude-chats`):**

| Model | Broken-MCP score | True baseline | Correct | Notable remaining failures |
|-------|------------------|---------------|---------|----------------------------|
| haiku  | 0.39 | **~0.67** (≈0.75 excl. 2 harness crashes) | 8/14 | Q9 Saudi retrieval miss; Q14 hallucinated adjacent detail; Q8 partial |
| sonnet | 0.45 | **~0.85** | 9/13 | Q6 "which Diego" false-gap; Q4 overstated stack |

The split-brain fix alone roughly doubled scores. This design targets the **genuine remaining
failures**, each traced to a specific code lever:

- **Q6 (even Sonnet false-gapped):** "Diego Albano" exists only inside a role page
  (`specialist,-solution-assurance.md`), never promoted to a person entity → name search cannot
  find him. **Root cause: consolidation fragmentation.**
- **Q9 (Haiku miss):** the A100/Dammam answer is in both the entity page and its episode, but
  Haiku's navigation didn't surface it. **Root cause: retrieval breadth + no episode fallback.**
- **Q14 (Haiku hallucinated):** invented an unrequested detail about the user's dad.
  **Root cause: weak grounding discipline in tool guidance.**
- **Q8 / Q4 (partials):** a Key-Facts detail dropped from the truncated summary / stack overstated.
  **Root cause: non-section-aware truncation.**
- **Archived suppression (Q10 ESA):** `search_entities(include_archived=False)` drops archived
  entities; currently *masked* by the keyword-search fallback (scans all files regardless of
  status), but paraphrased queries to archived entities still miss. **Root cause: archived blind
  spot.**

## 2. Scope & decisions (locked with Rodrigo, 2026-07-03)

- **Scope:** retrieval layer **and** consolidation self-heal (not the full G10 big-model rebuild).
- **Eval:** build a repeatable, committed harness in `benchmarks/`; personal questions stay in
  gitignored `*.local.yaml`.
- **Memory safety:** Phase 2 (which rewrites entity files) runs on a **duplicate bank**
  (`claude-chats-v2`, created via the existing banks feature), leaving the live bank untouched
  until Rodrigo approves the result by comparing scores.

**Non-goals:** G10 full-corpus big-model re-extraction; any change to the storage format
(markdown+git stays source of truth); any change to the closed 8-type taxonomy.

## 3. Success criteria

1. Re-run the harness after each phase; **target haiku ≥ 0.85, sonnet ≥ 0.92** average.
2. **Zero hallucinations** on negative-category questions (model must not invent adjacent facts).
3. Every "answer-is-in-memory" question is retrievable by *both* models (no false gaps on Q6/Q9).
4. No regression: negative questions still correctly return honest gaps; `/ask` and existing tests
   stay green.

## 4. Design

### Phase 0 — Eval harness (measurement backbone)

**Unit:** `benchmarks/run_retrieval_eval.py` (+ `benchmarks/questions.example.yaml` template;
real questions in gitignored `benchmarks/questions.local.yaml`).

- **What it does:** for each question × model, runs a real `claude -p --mcp-config <bank>
  --strict-mcp-config --allowedTools mcp__cicada` session, captures the answer, then scores it with
  an LLM judge against the rubric (`correct/partial/wrong/hallucinated/honest-gap/tool-failure`,
  0–1 score + failure diagnosis). Writes JSONL + a scoring CSV to gitignored `benchmark_results/`.
- **How you use it:** `make eval` / `python -m benchmarks.run_retrieval_eval --bank <path>
  --questions benchmarks/questions.local.yaml --models haiku,sonnet`.
- **Depends on:** a registered `cicada` MCP pointing at the target bank; the running/importable
  backend is not required (MCP is standalone).
- **Robustness:** the previous one-off runner crashed twice on unparseable tool calls; this runner
  captures subprocess stdout/stderr, treats a non-zero exit or empty output as `tool-failure`
  without aborting the batch, and supports `--repeat N` for noise averaging.
- **Privacy:** obeys the repo's `*.local.*` + `benchmark_results/` gitignore rules; the example
  file uses only neutral thesis-shaped placeholders.

### Phase 1 — Retrieval layer (no memory writes; touches read paths only)

**1a. Archived fallback tier** — `api/services/vector_index.py :: search_entities`.
Add a second pass: when the archived-filtered result set is thinner than `top_k`, re-query with
`include_archived=True` and append the archived hits **tagged with their status** so the caller can
label them "(decaying/archived)". Keep active entities ranked above archived. `search_claims` already
filters on validity, not entity status, so no change there.

**1b. Section-aware summary truncation** — `mcp/server.py :: _type_aware_truncate` /
`_truncate_to_desc_and_recent_history`. Replace byte-offset truncation with a section-aware version
that **always preserves `## Summary` and `## Key Facts`** (the fact-bearing sections) before applying
any length budget. Fixes Q8-type detail drops. A shared helper in `api/services/entity_body.py`
(which already owns the section grammar) is the natural home; the MCP calls it.

**1c. Breadth + rank fusion + episode fallback** — `mcp/server.py :: handle_recall`.
- Raise semantic/keyword `top_k` (5 → 8) and fuse the two lists with reciprocal-rank fusion instead
  of naive concat-dedupe, so a strong keyword hit and a strong vector hit reinforce.
- When entity hits are thin/low-score, add an **episode-search fallback** (`search_episodes` already
  exists) and surface the top episode snippet — Q9's answer lived in the episode.

**1d. Tool ergonomics & grounding** — `mcp/server.py` tool `description`s + `SKILL.md`.
- `cicada_recall`: instruct "if a fact might exist, call `cicada_recall_detail` on the top
  suggested entity before concluding it is absent."
- Add an explicit grounding line to `cicada_recall`/`cicada_ask`/`SKILL.md`: "State only facts
  present in tool results; do not add adjacent details from general knowledge." (fixes Q14.)
- Position `cicada_ask` as the recommended tool for direct factual questions (it reads full pages +
  claims internally and returns citations + honest gaps).

### Phase 2 — Consolidation self-heal (runs on duplicate bank `claude-chats-v2`)

**2a. Entity-merge primitive** — new `api/services/entity_merge.py :: merge_entities(memory_path,
loser_id, winner_id)`. Combines two rich pages: union of frontmatter (source_episodes, tags,
related, aliases), section-aware body merge (reuse `entity_body.merge_sections_human_safe`), union of
`` ```claims `` blocks, repoints `graph_edges.yaml` + wikilinks from loser→winner, deletes the loser,
commits with a `sleep/dedup` trigger + `user`/model author trailer. This is the primitive the backlog
(G21) says is missing — the current inbox "merge" only absorbs a *mention*.

**2b. Full-graph dedup sweep (G21)** — new `api/services/dedup_sweep.py`. Embedding-gate existing
same-type entity pairs (high cosine), LLM same/different/unsure judge with both pages' context,
auto-merge high-confidence via 2a, nudge the uncertain. Seed the first run with the known cases (the
three self-entities `rodrigo-jesus-sagastegui`/`user`/`rorosaga`; `esa`↔`esta`; `xrpl`↔`xrp-ledger`).

**2c. Relationship-target promotion** — a pass that promotes a person/org that is the *object* of a
high-confidence relationship/claim but has no page (e.g. "reports to **Diego Albano**"), creating a
backfilled stub entity so name-search resolves it. Fixes Q6.

**2d. Hub + `_index.md` regeneration** — run the existing `hub_builder` on the bank (live
`hubs/` is empty, `_index.md` absent), so recall's hub cold-start path becomes live.

**Ordering:** duplicate bank → 2b dedup → 2c promotion → 2d hub regen → rebuild vector index →
re-run eval on v2 vs original → Rodrigo promotes v2 if better.

## 5. Testing

- Every new service (`entity_merge`, `dedup_sweep`, promotion) gets hermetic TDD tests in
  `api/tests/` (throwaway memory dirs + fake embed/LLM, never touching live `memory/`), matching the
  repo's existing test style. Target: full suite stays green (currently 300).
- Phase 1 read-path changes get regression tests: archived entity retrievable via paraphrase;
  Key-Facts survives truncation; episode fallback fires when entities are thin.
- The eval harness is the integration-level check: score delta reported per phase.

## 6. Risks & mitigations

- **Merge corrupts a rich page** → section-aware merge preserves human prose (reuse the proven
  `merge_sections_human_safe`); runs on the duplicate bank; git-reversible.
- **Archived flood dilutes results** → archived hits are a *fallback* tier, rank-penalized and only
  appended when the active set is thin.
- **Eval noise** (LLM judge variance) → `--repeat` averaging; the judge rubric is fixed and the
  ground truth is human-verified per question.
- **Bigger recall payloads slow small models** → section-aware truncation keeps summaries bounded;
  measure token cost in the harness.

## 7. Deliverables

1. `benchmarks/run_retrieval_eval.py` + example questions template + `make eval` target.
2. Phase-1 retrieval changes (vector_index, mcp/server, entity_body, SKILL.md) + regression tests.
3. Phase-2 services (`entity_merge`, `dedup_sweep`, promotion) + tests, exercised on `claude-chats-v2`.
4. A before/after scoreboard per phase, written to `docs/goals/audit-2026-07/`.
