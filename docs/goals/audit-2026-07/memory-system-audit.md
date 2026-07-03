# Cicada Memory-System Audit — Final Report

**Scope:** Cicada repo, active bank `claude-chats` (memory/banks/claude-chats). Consolidation audit of the 2026-06-18 sleep cycles, 14-question retrieval eval (haiku vs sonnet), two write-path integration tests, and a code-level audit of the MCP/API bank routing.
**Date:** 2026-07-02

---

## 1. Executive Verdict

**Not launch-quality yet — but the failures are concentrated and mostly fixable in one week of targeted work, not a redesign.** Retrieval scored 0.39 (haiku) and 0.45 (sonnet) average across 14 questions, nearly all of which are answerable verbatim from the bank; on non-negative questions each model got only 2 of 12 fully correct. The dominant failure is not hallucination — both models were commendably honest, with zero fabricated facts on the negative probes — but *false gaps*: confidently declaring memory empty when the answer sits in an entity file. Three root causes drive this: (a) a confirmed high-severity split-brain where the MCP server serves the stale legacy root bank (no vector index, so semantic recall silently returns nothing) while the app serves `claude-chats`; (b) retrieval suppression of archived/low-confidence entities, which is where temporal decay puts exactly the long-tail facts users ask about; and (c) consolidation defects — the user split across three person entities, ESA fused into ESTA, duplicates created within a single cycle — that fragment the paths retrieval needs. The write path mechanically works (both tests passed, content-hash dedup works), but because of the split-brain, live MCP saves land in a bank the sleep cycle never processes: **new memories are currently being silently lost to consolidation.** The encouraging news: fact-level fidelity of consolidated pages is mostly good, temporal decay demonstrably works as designed, and the single MCP path-resolution fix would likely flip several eval failures to passes on its own.

---

## 2. Retrieval Scoreboard

| # | Question (abbrev.) | Category | Haiku | Sonnet |
|---|---|---|---|---|
| 1 | Holo-concierge internship — company's city | multi-hop | correct — 1.00 | honest-gap — 0.15 |
| 2 | Startup founder's precedent paper + results | multi-hop | partial — 0.40 | partial — 0.35 |
| 3 | Immigration firm contact + role | multi-hop | tool-failure — 0.00 | honest-gap — 0.10 |
| 4 | Pre-markdown storage stack + why dropped | temporal | honest-gap — 0.10 | correct — 0.85 |
| 5 | Work-permit send-off mid-April + next day | temporal | honest-gap — 0.15 | honest-gap — 0.35 |
| 6 | Which Diego is my MongoDB manager | disambiguation | honest-gap — 0.15 | honest-gap — 0.20 |
| 7 | Francesco vs Francisco at Tumi Robotics | disambiguation | partial — 0.60 | partial — 0.65 |
| 8 | Concert ticket seat (resale) | fact | correct — 1.00 | correct — 1.00 |
| 9 | Saudi doc-processing hardware + region | fact | honest-gap — 0.05 | honest-gap — 0.15 |
| 10 | Why ESA traineeship was rejected | fact | honest-gap — 0.10 | honest-gap — 0.15 |
| 11 | Freelance payment structure preference | preference | honest-gap — 0.00 | honest-gap — 0.15 |
| 12 | Thesis grammatical person preference | preference | honest-gap — 0.15 | honest-gap — 0.15 |
| 13 | My birthday (not in memory) | negative | honest-gap — 1.00 | honest-gap — 1.00 |
| 14 | Mom's name (not in memory) | negative | partial — 0.70 | correct — 1.00 |

**Per-model totals**

| Model | Avg score (all 14) | Avg excl. negatives (12) | correct | partial | honest-gap | tool-failure |
|---|---|---|---|---|---|---|
| haiku | 0.39 | 0.31 | 2 | 3 | 8 | 1 |
| sonnet | 0.45 | 0.35 | 3 | 2 | 9 | 0 |

**The haiku-vs-sonnet gap — can a small model navigate this memory?** The gap is only 0.06, and the evidence says the small model is not the bottleneck — the retrieval stack is. When retrieval surfaced the right content, Haiku matched Sonnet exactly (Q8) or beat it outright (Q1, where Haiku traced the full Triops→Caracas multi-hop through archived 0.04-confidence entities while Sonnet quit after two empty tool calls). Both models fail on the *same* questions for the *same* reason: the answer never comes back from the tools, either because the MCP is searching the wrong bank with no vector index or because archived/low-confidence entities are suppressed. Sonnet's edge is epistemics and persistence — it correctly disambiguated the two Diegos before abstaining (Q6), flagged the Francesco duplicate (Q7), and characterized reachable memory exhaustively (Q5) — but that discipline bought almost no score because the ceiling was set by the retrieval layer, not model capability.

**Most instructive failures:**

- **Q2 (founder's paper) — both models, worst failure mode in the set.** Both resolved the multi-hop correctly, retrieved content *adjacent* to the answer, then confidently declared the results "not in memory" — while `diego-sanmartín.md` Key Facts states "19% EM, 25% F1" verbatim. Diagnosis: chunk-level retrieval returned summary-only content and neither model read the full entity before asserting a gap. A false-negative about memory contents is worse than an honest gap — it teaches the user their memory is emptier than it is. Sonnet additionally fabricated a nonexistent "Diego's paper" decaying entity — the only memory-metadata hallucination observed.
- **Q10 (ESA rejection) — both models, identical miss.** The full answer is in `esa-graduate-trainee-programme.md`, but the entity is archived at confidence 0.0 and never surfaced. An identical miss by both models points to a systematic retrieval filter on archived/zero-confidence entities. This is a design tension: decay is working as intended, but "why was I rejected?" is exactly the kind of question users ask about decayed memories.
- **Q6 (which Diego) — consolidation defect causing retrieval failure.** The answer only exists inside a role page (`specialist,-solution-assurance.md`: "reports to Diego Albano"); no `diego-albano.md` person entity was ever promoted (he sits in `pending_entities.jsonl`), so person-name search cannot succeed by design. An unmerged "Diego Albania" typo entity actively pulled both models toward a grounded-but-wrong answer.
- **Q5 (work permit) — harness/split-brain casualty, should be voided.** The ground truth lives only in the bank's `hqp-permit.md`, which the bank-unaware MCP server literally cannot see. Both scores measure misconfiguration, not model or memory quality. Q7 shows forensic evidence of the same wrong-bank routing (Haiku cited the legacy copy's 0.82 confidence, not the bank's 0.29). Re-run Q1, Q3, Q5, Q7, and Q9–Q12 after the routing fix before drawing final retrieval conclusions.

---

## 3. Consolidation Quality — 2026-06-18 Sleep Cycles

**Verdict: Mixed — fact-level extraction is trustworthy, consolidation-level resolution (Stage 2) is the weak link and is not launch-quality.** Three sleep commits (66e1e5d, 55037e8, 4373387) wrote the entire bank: 1,036 entity files from 208 episodes. Of 27 deep-sampled pages, most are faithful to their source episodes, and the decay lifecycle demonstrably works (one-off trivia like `microfiber-cloth.md` auto-archived at confidence ~0.007 while multi-episode entities held 0.9). But the cycle systematically failed at knowing when two things are the same and when they are different.

**Worst issues:**

- **Entity fusion (high):** `esta.md` merges the US travel authorization with the European Space Agency — a visa query now returns space-agency career facts. `usd.md` conflates fiat salary with a stablecoin.
- **The user is split three ways (high):** `rodrigo-jesus-sagastegui.md`, `user.md`, and `rorosaga.md` each hold a different slice of his relationships. The graph's central node is fractured, and the dedup scan missed it.
- **Same-cycle duplicates (high):** `unidentified-space-company.md` vs `intuitive-machines.md` created from the *same episode* whose header literally names the company; `xrpl.md`/`xrp-ledger.md` carry mutual aliases — the strongest possible merge signal — and were still missed.
- **A false belief about the user's own thesis (high):** the Stage-4 skill `developing-cicada-with-a-graph-plus-document-architecture.md` asserts Cicada uses "Neo4j, MongoDB, and Supahost" — flatly wrong — with `source_episodes: []`, so it's unfalsifiable. All 11 Stage-4 skills lack provenance, defeating the system's core guarantee.
- **Missing central node (high):** `[[Cicada]]` is wikilinked from 62 pages but has no entity, while a queen-sized mattress and 70% isopropyl alcohol got full pages. Promotion prioritization is inverted.
- **Systemic hygiene (medium):** 32 entities use types outside the closed 8-type schema (`directory`, `feature` — breaking the app's coloring/filtering contract); 80 pages have orphaned `- id: clm_...` lines corrupting Key Facts; 1,874 of 1,879 claims sit at exactly confidence 0.6 (no calibration signal); Stage 3 appends summaries instead of reconciling them (`mongodb-return-offer.md` states two different start dates in one page).

**Good examples worth keeping as reference outputs:** `raul-perez-pelaez.md` (verbatim-faithful, correctly low confidence for a single mention); `intuitive-machines.md` (every number traces to the episode, nuanced "sold too early" summary, correct decay to archived); `embedding-similarity-classification.md` (dense technical capture including the rejected alternative — exactly what consolidation should produce); the `matthew-petersen.md` / `matthew-petersen-portfolio.md` person/project decomposition; and the decay pipeline end-to-end.

---

## 4. Write Path

Both `save_episode` tests **passed**.

- **Hermetic test (scratch clone):** Haiku session saved `ep_2026-07-03_001.md` with correct frontmatter (`processed: false`, `source: mcp`, `content_hash`). An identical second save was correctly rejected — "Episode already exists (duplicate detected by content hash)". Dedup is exact-content sha256[:12] with a linear scan of all episode files per save (fine at current scale). Live bank untouched.
- **Live test (real registration, byte-identical mirror of `~/.claude.json` config):** end-to-end save through a real `claude -p` session succeeded; exactly one file created, frontmatter verified, no commit made at save time (correct — commits belong to Sleep), cleanup restored byte-identical git state.

**Caveats found during testing:** (1) timestamps are naive local time with a hardcoded `Z` suffix (`mcp/server.py:1048`), falsely claiming UTC; (2) episode IDs use `len(existing)+1` per day, which can collide if a same-day file is deleted; (3) a stale broken `cicada-bookworm` MCP registration lingers in `~/.claude.json` under the old project path. **Critical context:** the live test wrote to `memory/episodes/` — the root bank — which, per Section 5, means live MCP saves are never consolidated while `claude-chats` is active. The write mechanism passes; the write *destination* is wrong.

---

## 5. Bank Split-Brain and Write-Path Code Findings

**Split-brain confirmed with on-disk evidence.** The MCP and the API interpret the same env var (`CICADA_MEMORY_PATH=.../memory`) differently, and are serving two different knowledge graphs simultaneously.

| # | Severity | Finding |
|---|---|---|
| 1 | **High** | **MCP is bank-unaware.** `get_memory_path()` (`mcp/server.py:223-229`) returns `CICADA_MEMORY_PATH` verbatim, never consulting `banks.yaml`; the API resolves the same var through `bank_registry.resolve_active_bank_path` (`api/config.py:33-41`). Result: every filesystem-backed MCP tool (`cicada_recall`, `recall_detail`, `open_hub`, `get_perspective`, `check_nudges`, `save_episode`) serves the legacy root bank (1,882 entities, 117 episodes) while the API/app serve `banks/claude-chats` (1,036 entities, 208 episodes). |
| 2 | **High** | **MCP saves are never consolidated.** `handle_save_episode` writes to `memory/episodes/` (root), but the sleep cycle scans `settings.memory_path` — the active bank (`sleep_cycle.py:76`). MCP-captured episodes sit at `processed: false`, invisible to every sleep cycle. Silent memory loss. |
| 3 | **High** | **`cicada_ask` is internally inconsistent.** Backend-up path POSTs to `/ask` and answers from the active bank; backend-down fallback calls `ask_service.answer_query(get_memory_path())` — the root (`server.py:281-316`). Same question, two different graphs, depending on whether uvicorn happens to be running. `handle_save_url` has the identical dual behavior, including split URL-dedup indexes. |
| 4 | **Medium** | **Semantic recall is silently dead in the MCP.** `SqliteVecIndexer` looks for `<memory_path>/vector_index.db`; no such file exists at the root — the only real index (30 MB) is in the bank the MCP never reads. Missing DB and swallowed exceptions both return `[]`, so recall degrades to keyword scan over the stale root graph with zero error surfaced. This directly explains multiple eval honest-gaps. |
| 5 | **Low** | **install.sh contract is fine; the MCP violates it.** The installer registers the root under one variable with one meaning; the bug is solely the MCP's missing resolution step. Do *not* "fix" by registering `banks/claude-chats` directly — that freezes the bank at install time and re-splits on the next bank switch. |

---

## 6. Top 7 Prioritized Recommendations

1. **Fix `get_memory_path()` in `mcp/server.py` to resolve `banks.yaml` exactly like the API** (import `resolve_active_bank_path` with a try/except fallback to the raw path). This one change collapses findings 1–4: recall, ask fallback, save_url, save_episode, and the vector index all snap to the active bank, with live bank-switch semantics. Do not re-register the MCP with a bank path. Highest-leverage fix in this entire report.
2. **Sweep stranded MCP episodes into the active bank.** After the fix, move `memory/episodes/` files with `source: mcp` + `processed: false` written since 2026-06-17 into `banks/claude-chats/episodes/` so they get consolidated. Then re-run the affected eval questions (Q1, Q3, Q5, Q7, Q9–Q12) — current retrieval scores understate the system.
3. **Repair Stage 2's worst resolution failures by hand, then harden the rules.** Merge the three user self-entities, `xrpl`/`xrp-ledger`, `unidentified-space-company`→`intuitive-machines`, and Diego Albania/Albano; split ESA out of `esta.md` and the stablecoin out of `usd.md`. Add two cheap automatic rules: mutual aliases always propose a merge, and a within-cycle same-episode dedup pass before writing.
4. **Make retrieval able to reach archived/low-confidence entities.** Q9/Q10 show a systematic filter: decayed memories (confidence ≤0.2, absent from `_index.md`/hubs) are exactly what long-tail questions target. Add a second-pass fallback tier (search archived entities when the active pass returns nothing) and have MCP recall output distinguish "no index" from "no hits" instead of silently returning empty.
5. **Enforce schema and provenance at write time.** Reject or queue entities with types outside the closed 8-type set (32 offenders, including raw filesystem paths), and require non-empty `source_episodes` on Stage-4 skills — the current 11 provenance-free skills include a false belief about the thesis's own stack. Route unnamed/unknown entities ("Friend (concert trip companion)") to the clarification queue instead of the graph, per Cicada's own design.
6. **Replace Stage 3's append-only summary stitching with rewrite-and-reconcile,** and fix the claims-merge formatter that left orphaned `clm_` lines in 80 files. Pages like `mongodb-return-offer.md` should carry one reconciled summary and one start date, not three stitched paragraphs with an unresolved contradiction. Also create the missing `Cicada` entity (62 dangling wikilinks).
7. **Write-path and hygiene polish:** use `datetime.now(timezone.utc)` for episode timestamps (the current local-time-plus-`Z` will corrupt temporal reasoning), make episode-ID assignment collision-safe (max existing suffix + 1, not count), remove the stale `cicada-bookworm` registration, calibrate claim confidence (1,874/1,879 at exactly 0.6 carries no signal), and stop conflict nudges treating non-exclusive predicates like `uses` as single-valued (source of the 3,375-item dismissal noise).

---

*Bottom line: consolidation extracts truthfully but resolves poorly; retrieval is honest but throttled by a wrong-bank MCP and an archived-entity blind spot; writes work but currently land where Sleep never looks. Fix the routing first — it is one function — then re-measure before judging the rest.*