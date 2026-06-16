# Cost model for memory reconsolidation

> Research note (r5). Author: subagent for Rodrigo Sagastegui. Date: 2026-06-16.
> Scope: estimate token volume and $ to RE-consolidate Cicada's memory (re-run the
> Sleep cycle / re-extract the corpus) across model tiers, and propose a financing/
> reconsolidation policy. Decisions this informs: none are blocking — D1/D2/D4 are
> research-only; this note is input, not a commitment.
>
> Confidence labels used below: **[measured]** = read from the live repo;
> **[priced]** = current published per-token rates (verified 2026-06-16);
> **[modeled]** = my estimate from stated assumptions — the soft part; **[unverified]**
> = directional, sanity-check before quoting in the thesis.

## TL;DR

- **A full reconsolidation of the current corpus (1,882 entities + 117 episodes,
  ~3.5M chars ≈ ~0.9M raw tokens) costs roughly $1–4 on cheap tiers (Haiku 4.5 /
  GPT-5-mini) and $5–18 on Sonnet, per full pass** — but token *throughput* is
  dominated by re-extraction prompt overhead, not the corpus text itself, so the
  real number is **~3–9M billed input tokens / ~0.5–1.5M output tokens per full run**
  **[modeled]**. This is cheap enough that cost is *not* the binding constraint —
  wall-clock time and quality variance are.
- **Recommended policy: cheap-tier-first, selective-Opus, incremental-by-default.**
  Run the nightly Sleep cycle on a cheap tier (Haiku 4.5 or GPT-5-mini), reserve
  Sonnet/Opus for (a) conflict resolution + entity disambiguation, the two stages
  where a wrong call corrupts the graph, and (b) periodic full reconsolidations.
  Full re-extraction from scratch should be **rare and event-triggered**, not scheduled.
- **Use the Batch API for any full reconsolidation: flat 50% discount, and the
  workload is inherently non-latency-sensitive** (it's an offline batch job already).
  This roughly halves the full-pass cost to **~$0.5–2 (cheap) / $3–9 (Sonnet)** **[priced]**.
- **The corpus is model-agnostic at the code layer** (the pipeline calls LiteLLM via
  `settings.litellm_model` — verified in `entity_extractor.py`, `conflict_resolver.py`,
  `skill_extractor.py`), so tier-switching and per-stage model routing are config
  changes, not rewrites. That makes "cheap-tier-first then selective-Opus" basically free
  to implement. **[measured]**
- **Biggest cost lever is prompt caching, not model choice.** Re-extraction re-sends
  large stable context (the existing graph, the extraction schema/prompt) on every call.
  Anthropic prompt caching discounts repeated prefixes ~90% on reads; OpenAI auto-caches
  at 75–90%. Structured correctly this cuts full-pass input cost more than dropping a
  whole model tier. **[priced]**

## Findings

### 1. The corpus, measured

From the live `memory/` directory (`feat/v2-revamp`, 2026-06-16) **[measured]**:

| Bucket | Count | Total chars | On-disk |
|---|---|---|---|
| Entity pages (`entities/*.md`) | 1,882 | ~1.22M | 7.4 MB |
| Episodes (`episodes/`) | 117 files | ~2.28M | 2.4 MB |
| **Raw text in scope** | — | **~3.5M chars** | — |
| Whole `memory/` tree | — | — | 38 MB (incl. LEANN index, git) |

**Char→token conversion.** English prose/markdown is ~3.5–4 chars/token on the
Claude Opus 4.7+ tokenizer family (and that tokenizer runs ~30% *more* tokens than
pre-4.7 models per Anthropic's overview note — relevant because Sonnet 4.6 / Opus 4.8
use it). Taking **~3.8 chars/token** **[modeled]**:

- Entities: 1.22M / 3.8 ≈ **~320K tokens**
- Episodes: 2.28M / 3.8 ≈ **~600K tokens**
- **Total raw corpus ≈ ~0.9M tokens** (call it 0.85–1.0M). **[modeled]**

This raw number is the floor. It is *not* what you get billed, because re-extraction
multiplies it (next section).

### 2. Why billed tokens ≫ raw corpus tokens

A full reconsolidation re-runs the 5-stage Sleep pipeline over every episode. The
pipeline (verified file-by-file in `api/services/`) makes **multiple LLM calls per
episode and per entity cluster**, and each call re-sends overhead that the corpus text
alone doesn't capture:

1. **Extraction** (`entity_extractor.py`): per-episode call with the extraction
   schema + few-shot + the episode chunk. Schema/instructions are fixed overhead
   (~1–3K tokens) re-sent on *every* episode call.
2. **Resolution / disambiguation** (`entity_resolver.py`): per candidate-entity LLM
   disambiguation. Each call ships candidate context + nearby existing-graph entities
   for the "Mongo → MongoDB / the project → which project" decision. This is the call
   that re-reads chunks of the *existing 1,882-entity graph*.
3. **Conflict resolution** (`conflict_resolver.py`): two LLM call sites (lines 545,
   594) per conflicting cluster — re-reads competing entity states.
4. **Skill / pattern extraction** (`skill_extractor.py`): scans across episodes.
5. **Nudge / clarification generation**: lighter, mostly templated, some LLM.

**Modeled token volume for one full pass [modeled / unverified]:**

| Component | Calls | ~Input tok/call | ~Output tok/call | Input subtotal | Output subtotal |
|---|---|---|---|---|---|
| Extraction (per episode) | ~117 | ~6K (chunk + schema) | ~2K | ~0.7M | ~0.23M |
| Resolution/disambig (per new/changed entity) | ~1,900 | ~3K (candidate + graph nbrs) | ~0.4K | ~5.7M | ~0.76M |
| Conflict resolution (per cluster) | ~150 | ~5K | ~0.6K | ~0.75M | ~0.09M |
| Skill/pattern | ~40 | ~8K | ~1K | ~0.32M | ~0.04M |
| Nudges/clarifications | ~120 | ~2K | ~0.3K | ~0.24M | ~0.04M |
| **Full pass total** | ~2,300 calls | — | — | **~7.7M input** | **~1.16M output** |

The disambiguation stage dominates because it scales with **entity count (1,882)**,
not episode count. This is the single most important fact for the cost model:
**reconsolidation cost scales with graph size, and the graph only grows.** A 10K-entity
graph in two years is a ~5× more expensive full pass, all else equal.

> Caveat: the per-call token figures are estimates from reading the prompt-construction
> code's *shape*, not from instrumented runs. To get a real number, run
> `benchmarks.run_table3` with token accounting on a `/tmp/cicada_bench_*` workspace
> and read actual `usage` off the LiteLLM responses. **Do this before quoting any
> dollar figure in the thesis.** **[unverified]**

### 3. Current per-token prices (verified 2026-06-16)

**Anthropic Claude** (per 1M tokens, input / output) — verified against
`platform.claude.com/docs/en/about-claude/models/overview` **[priced]**:

| Model | Input $/MTok | Output $/MTok | Context |
|---|---|---|---|
| Claude Haiku 4.5 | $1.00 | $5.00 | 200K |
| Claude Sonnet 4.6 | $3.00 | $15.00 | 1M |
| Claude Opus 4.8 | $5.00 | $25.00 | 1M |
| (Claude Fable 5) | $10.00 | $50.00 | 1M |

**OpenAI cheap options** (per 1M tokens, input / output) — from current pricing
aggregators (CloudZero, aipricing.guru, pricepertoken), 2026 rates **[priced /
unverified — confirm on platform.openai.com before quoting]**:

| Model | Input $/MTok | Output $/MTok | Notes |
|---|---|---|---|
| GPT-4.1-nano | $0.10 | $0.40 | cheapest; weakest extraction |
| GPT-5.4-nano | $0.20 | $1.25 | |
| GPT-5-mini | $0.25 | $2.00 | good cheap-tier extraction baseline |
| GPT-4.1-mini | $0.40 | $1.60 | |
| GPT-5.4-mini | $0.75 | $4.50 | |

**Discounts that apply to reconsolidation [priced]:**
- **Batch API**: flat **50%** off input+output, both Anthropic and OpenAI. The Sleep
  cycle is an offline batch job, so this is a near-free win for full reconsolidations.
- **Prompt caching**: Anthropic ~90% off cached-read input (write costs 1.25×);
  OpenAI auto-caches repeated prefixes at 75–90% off. Applies to the *stable* parts
  of each call (schema, graph context).

### 4. Dollar cost per full reconsolidation [modeled]

Using the ~7.7M input / ~1.16M output modeled volume from §2, **no caching, no batch**:

| Tier | Input cost | Output cost | **Full pass** |
|---|---|---|---|
| GPT-4.1-nano | $0.77 | $0.46 | **~$1.2** |
| GPT-5-mini | $1.93 | $2.32 | **~$4.3** |
| Haiku 4.5 | $7.70 | $5.80 | **~$13.5** |
| Sonnet 4.6 | $23.10 | $17.40 | **~$40.5** |
| Opus 4.8 | $38.50 | $29.00 | **~$67.5** |

> Note: Haiku looks *more* expensive than GPT-5-mini here purely on sticker rate
> ($1/$5 vs $0.25/$2). On the cheap Anthropic tier, GPT-5-mini wins on price; Haiku
> wins on staying inside one provider/SDK and on the Anthropic prompt-cache mechanics.

**With Batch API (−50%) and prompt caching on the ~60% of input that's stable
context (−~85% on that portion):**

Effective input multiplier ≈ (0.4 full + 0.6 × 0.15) × 0.5 ≈ **~0.245×**.
Output ×0.5.

| Tier | **Full pass, batched + cached** |
|---|---|
| GPT-5-mini | **~$1.3** |
| Haiku 4.5 | **~$4** |
| Sonnet 4.6 | **~$12** |
| Opus 4.8 | **~$20** |

**Bottom line: a full reconsolidation is a single-digit-to-low-double-digit-dollar
event on quality tiers, and a coffee on cheap tiers.** Cost is not the constraint.
Time and quality variance are.

### 5. What actually constrains reconsolidation (it isn't dollars)

- **Wall-clock**: ~2,300 sequential LLM calls. Even at 2s/call with modest
  concurrency, a full pass is tens of minutes to a couple of hours. The Batch API
  makes this *worse* for latency (up to 24h turnaround) but is fine because it's offline.
- **Quality variance on cheap tiers**: the two stages where a cheap model corrupts
  the graph are **entity resolution/disambiguation** and **conflict resolution**. A
  wrong merge ("are these the same person?") or a wrong recency-wins call writes bad
  state that the *next* cycle then builds on. This is the real argument for selective-Opus.
- **Graph-size scaling**: as established, cost and time grow with entity count. A
  policy that does full re-extraction nightly does not scale; an incremental one does.

## What this means for Cicada

1. **Default to incremental, not full.** The entity-promotion + `processed: false`
   design already supports this — only unprocessed episodes hit the LLM each night.
   A full reconsolidation (re-extract *everything* from raw episodes, rebuild the
   graph) should be an **occasional, deliberate, event-triggered** operation, not the
   nightly default. Triggers worth defining: (a) a prompt/schema change that makes old
   extractions stale, (b) a model-tier upgrade you want applied retroactively, (c) a
   suspected systemic extraction bug, (d) a thesis benchmark run that needs a clean,
   uniformly-extracted graph.

2. **Route models per-stage, cheap-first.** Because the pipeline already reads
   `settings.litellm_model`, you can introduce per-stage overrides cheaply:
   - Extraction, skill/pattern, nudges → **cheap tier** (GPT-5-mini or Haiku 4.5).
     These are high-volume, low-stakes-per-call; a miss costs one re-mention.
   - Entity resolution/disambiguation + conflict resolution → **Sonnet (default) or
     Opus (when the graph is large/valuable)**. These are the corruption-risk stages.
   - This is the concrete "cheap-tier-first then selective-Opus" the task asks for,
     and it's a `disambig_model` / `conflict_model` config split, which the
     `entity_resolver.py` code already half-anticipates (it computes a separate
     `disambig_model`). **[measured]**

3. **Make every full reconsolidation a Batch job.** It's offline by definition.
   Flat 50% is the single biggest no-downside discount available. The only cost is
   turnaround latency, which doesn't matter for a nightly/occasional batch.

4. **Invest in prompt-cache hygiene before investing in a bigger model.** The
   disambiguation stage re-sends graph-neighbor context on ~1,900 calls. If that
   context is structured as a stable cacheable prefix (graph snapshot first, varying
   candidate last), Anthropic/OpenAI caching cuts the dominant input cost ~85% on the
   stable portion — a larger saving than dropping Sonnet→Haiku. This aligns with the
   prompt-caching prefix-match invariant (stable content first, volatile last).

5. **Budget for graph growth.** Put the *per-entity* reconsolidation unit cost in the
   thesis (e.g. "~$0.002–0.006/entity for a full cheap-tier pass" **[modeled]**), not
   just a single total, because the total is a moving target. A per-entity figure is
   what lets a reader reason about a 10K- or 100K-entity future.

## Recommendation

**Adopt a tiered, incremental-by-default reconsolidation policy:**

1. **Nightly Sleep cycle → cheap tier, incremental.** Process only unprocessed
   episodes. Extraction/skill/nudge stages on **GPT-5-mini or Haiku 4.5**. Cost per
   night is cents.
2. **Corruption-risk stages → Sonnet by default, Opus on demand.** Route
   `disambig_model` and the conflict-resolver model to **Sonnet 4.6** always; promote
   to **Opus 4.8** only for full reconsolidations or once the graph passes a size
   threshold (e.g. >5K entities) where a bad merge is expensive to unwind.
3. **Full reconsolidation → event-triggered, Batch API, cached.** Not scheduled. Run
   it on prompt/schema changes, model upgrades, or before a thesis benchmark snapshot.
   Always via Batch API (−50%) with prompt-cached stable context. Budget **~$1–4
   (cheap) / ~$10–20 (Sonnet/Opus)** per full pass at current corpus size **[modeled]**.
4. **Instrument real token usage now.** Add `usage` accounting to the LiteLLM calls
   and capture it in `benchmarks.run_table3` so the thesis quotes *measured* numbers,
   not my modeled ones.

Concretely, the recommended call is: **cheap-tier-first + selective-Sonnet/Opus on the
two graph-integrity stages + incremental nightly + occasional batched full passes.**
This minimizes both dollar cost and graph-corruption risk, and it's almost entirely a
config change given the existing LiteLLM indirection.

## Open questions (need Rodrigo's input)

1. **What is the *real* per-stage token volume?** My §2 numbers are modeled from
   reading prompt-construction code, not instrumented runs. Need one real Batch/full
   run with `usage` captured to replace [modeled] with [measured]. Will you run
   `benchmarks.run_table3` with token accounting before the thesis Results section?
2. **What is the actual reconsolidation trigger you want for the thesis demo?** A
   scheduled full reconsolidation makes a clean benchmark but doesn't reflect the
   intended steady-state (incremental). Which do you want to *report* — full-pass cost
   (clean, comparable) or steady-state nightly cost (realistic, tiny)? They tell
   different stories.
3. **Single-provider or mixed?** Cheapest is OpenAI nano/mini for bulk + Anthropic
   Sonnet/Opus for integrity stages — but that's two SDKs, two billing accounts, two
   prompt-cache mechanics. Is the operational simplicity of staying all-Anthropic
   (Haiku + Sonnet + Opus) worth the ~3–4× higher cheap-tier sticker price? At these
   absolute dollar levels I lean all-Anthropic; confirm.
4. **OpenAI prices are from aggregators, not the source.** Verify GPT-5-mini /
   GPT-4.1-nano / GPT-5.4 rates on platform.openai.com before any number goes in the
   thesis — aggregator pricing drifts.
5. **Do you ever need to reconsolidate the LEANN index too?** This note covers the
   LLM extraction/graph cost only. A full re-embed of the episode corpus is a separate
   (much smaller) cost — `benchmarks.rebuild_leann` is noted in CLAUDE.md as "a few
   cents of text-embedding-3-small." Worth folding into the full-reconsolidation
   budget line, but I scoped it out here.

Sources: [Claude models overview/pricing](https://platform.claude.com/docs/en/about-claude/models/overview),
[CloudZero OpenAI pricing 2026](https://www.cloudzero.com/blog/openai-pricing/),
[aipricing.guru OpenAI](https://www.aipricing.guru/openai-pricing/),
[pricepertoken GPT-5-mini](https://pricepertoken.com/pricing-page/model/openai-gpt-5-mini).
