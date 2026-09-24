# Memory benchmarks and implicit recall

**Date:** 2026-09-24 · **Rows:** [G148](../goals/memory-evolution.md) (benchmark pass),
[G149](../goals/memory-evolution.md) (implicit recall through hooks) · **Status:** research, nothing built.

**Why this exists.** The owner read Dhravya Shah's post of 2026-02-17 about memory for coding agents
(x.com/DhravyaShah/status/2023630749065228364) and asked two things: *"I think we use tool calls right?
but then we depend on the model they are using being good and smart, no?"* and *"research how these
guys do their memory benchmarks to see if maybe we could run a pass for cicada."* This note answers
both and proposes the work.

**Citation rules.** Cicada code is cited as repo-relative `file:line` on `dev` at `ecb59c7`. MemoryBench
is cited at commit `94e2af5` (default branch on 2026-09-24), shortened below as
`MB/<path>:<line>` = `https://github.com/supermemoryai/memorybench/blob/94e2af54b661d90e77dddbd8fa4fa5b28c07a24e/<path>`.
The post itself returned HTTP 402 to a fetch, so its claims are taken as relayed to this session and
are marked that way. No bank data, no `~/.cicada`, no harness transcripts were read.

---

## Short answer

1. **Half right, and the half that matters most is already fixed.** Capture never depends on a model
   calling a tool: the harness's own `Stop` hook saves every Claude Code and Codex session (G105).
   Consolidation, decay and dedup run in Sleep on Cicada's own engine, not the chat model. **Recall
   still does depend on the model.** `cicada_recall`, `cicada_ask` and the rest are MCP tools. A model
   that doesn't call them gets nothing from Cicada on that turn, and nothing records that it happened.
2. **The post's benchmark numbers don't measure that argument.** MemoryBench calls every provider's
   `search()` on every question, with no exceptions. The 58.3% "RAG" figure is already the best case,
   where the tool always runs. The 27.6-point gap to Supermemory comes from extraction and retrieval
   quality, not from hooks versus tools.
3. **Cicada can run a fair pass, but not yet.** One throwaway bank per conversation, with no link to the
   owner's bank or `~/.cicada`. Two recall modes (hooks and tools), a full-context control, and runs
   both with and without Sleep. Scores are reported per category. Three things block it:
   - the existing harness ignores the throwaway path it builds (verified below);
   - Sleep's "today" is the wall clock, so expiry and decay run as of 2026 against a 2023 dataset
     (decay is capped at 7 days a cycle, so this is a slow skew, not an instant archive — see below);
   - the Sleep engine must be pinned, or a benchmark spends plan quota.
4. **Recall can be made implicit the same way capture was.** A `SessionStart` hook injects the handshake.
   A `UserPromptSubmit` hook injects a small, budgeted recall block before the model reads the prompt.
   Claude Code and Codex use the same output shape for both hooks. G148's two modes are how we'd
   measure whether it helps.

---

## (a) The post: its argument, its numbers, and what to discount

**The argument, as relayed.** OpenClaw's memory "uses tools, not hooks". Every save and every recall
depends on the main agent choosing to call a tool. That costs tokens and time, and it fails silently
when the agent doesn't call. The post adds that OpenClaw's memory:

- does not handle knowledge updates, temporal reasoning or multi-session context;
- stores redundant facts, because it doesn't know what is already stored;
- never forgets.

Supermemory's plugin uses hooks instead. Saves happen in the background, as extracted memories plus raw
chunks. Recall is injected before the model answers, and irrelevant information decays. Tools remain
for deep dives.

**The numbers, as relayed.** On Supermemory's open-source MemoryBench:

| System | Score |
|---|---|
| Filesystem ("Claude Code's memory") | 54.2% |
| RAG ("OpenClaw's memory, assuming the tool is called") | 58.3% |
| Supermemory | 85.9% |

**What holds.** The architectural point is sound, and it doesn't need the numbers. Two independent
sources support it:

- **Cicada's own G105 row.** Before the Stop hook existed, the MCP server logged zero tool invocations
  across 12 days (`docs/goals/memory-evolution.md:669`).
- **Letta's leaderboard** (https://www.letta.com/blog/letta-leaderboard/). It scores memory operations
  per answer model and penalizes unnecessary memory-tool calls. The quality of a tool-call memory
  depends on which model drives it.

**What to discount, in order of weight:**

1. **The numbers don't test the claim they illustrate.** MemoryBench's orchestrator runs the search
   phase (`MB/src/orchestrator/index.ts:268-276`), which calls `provider.search()` directly for every
   pending question with a fixed `limit: 10, threshold: 0.3` (`MB/src/orchestrator/phases/search.ts:23-62`).
   No model ever decides whether to search. The "tool is not
   called" failure the post leads with never occurs in this benchmark. That is why the RAG row is
   labelled "assuming the tool is called". The gap between the rows measures extraction, retrieval and
   answer quality with retrieval always on.
2. **"Filesystem" is the vendor's own strawman of Claude Code's memory.** The baseline's comment says it
   implements "the Claude Code MEMORY.md approach" (`MB/src/providers/filesystem/index.ts:69`). What it
   actually does:
   - `gpt-4o-mini` extracts one flat markdown file per session (`MB/src/prompts/extraction.ts:6,40-53`);
   - search scores each file by the fraction of query words it contains as substrings, plus a
     frequency bonus capped at 0.1, over every file (`MB/src/providers/filesystem/index.ts:23-64,140-189`);
   - there are no embeddings, no BM25, no consolidation and no dedup.

   Claude Code's real auto-memory is written by the agent and loaded at session start (see G131). The
   baseline is neither of those.
3. **"RAG" is the vendor's reimplementation of OpenClaw, not OpenClaw.** It uses the same per-session
   extraction, ~400-token chunks and `text-embedding-3-small`. Its index is in memory only
   (`MB/src/providers/rag/search.ts:9`). It fuses `0.7·cosine + 0.3·BM25` with hardcoded weights, which
   its own comment says follow "OpenClaw's formula" (`MB/src/providers/rag/index.ts:18-25,72-86`,
   `MB/src/providers/rag/search.ts:257-260,315-334`). Whether it matches OpenClaw's real behaviour was
   not checked (inferred: no tuning appears in the repo).
   - **Each provider also brings its own answer prompt** (`answerPrompt` in
     `MB/src/providers/{supermemory,filesystem,rag}/prompts.ts`, used by
     `MB/src/orchestrator/phases/answer.ts:49-68`). The rows therefore differ in the prompt that turns
     retrieved context into an answer, not only in retrieval.
4. **Supermemory's own leg is opaque.** Its provider sends raw sessions to Supermemory's API and
   searches with the product's server-side hybrid ranking (`MB/src/providers/supermemory/index.ts:36-59,120-136`).
   None of that pipeline can be read or reproduced from the repo. `clear()` is a logged no-op
   (`MB/src/providers/supermemory/index.ts:138-141`), so Supermemory containers are never cleaned up.
   Containers are keyed `<questionId>-<dataSourceRunId>` (`MB/src/orchestrator/phases/ingest.ts:44`), and
   a copied run reuses its source's `dataSourceRunId` (`MB/src/orchestrator/checkpoint.ts:137,350-353`),
   so a re-ingest into an existing container would add to it (inferred, not run).
5. **The published run can't be reproduced from the repo.** `grep -rn "54.2\|58.3\|85.9"` over the
   repo at `94e2af5` finds no committed report. The relay also doesn't say:
   - which of the three datasets was used;
   - which answer or judge model ran;
   - which commit was run.

   The defaults are `gpt-4o` for both answering and judging (`MB/src/utils/models.ts:230`,
   `MB/src/cli/commands/run.ts:12,183`, `MB/src/judges/README.md:55-61`).
   - **Its LoCoMo adversarial category is graded against the string `"undefined"`.** The loader sets
     `groundTruth: String(qa.answer)` (`MB/src/benchmarks/locomo/index.ts:133`), and 444 of the 446
     category-5 questions in `locomo10.json` have no `answer` field, only `adversarial_answer` (counted
     2026-09-24 from the file the loader downloads, sha256 `79fa87e9…`). Any LoCoMo figure from this
     harness that includes that category inherits this.
   - **Its own docs disagree on LoCoMo's categories.** The loader maps category 2 → multi-hop and
     3 → temporal (`MB/src/benchmarks/locomo/index.ts:69-75`); `MB/framework.md:153-160` maps Cat 3 →
     MULTI_HOP and Cat 2 → TEMPORAL. Per-category LoCoMo numbers need the mapping stated.
6. **The vendor wrote the harness, picked the baselines, set the judge default and wins by 27 points.**
   That's the pattern that section (c) lists as the field's most common pitfall. Treat the numbers as a
   claim to re-run, not a target.

**Where the post's other planks land on Cicada:**

- **Redundant facts.** Sleep's Stage 2 resolves entities and Stage 3 resolves conflicts, and the claim
  layer keys beliefs by `(subject, predicate)`. Both run in batch whether or not an agent called a tool.
- **Forgetting.** Decay classes (`api/services/decay_policy.py`) and archive thresholds handle it. Silence
  is a designed signal.
- **Knowledge updates and time.** The claim layer carries bi-temporal validity, and newer claims
  supersede older ones.

None of these has been measured on a public dataset. That gap is G148's reason to exist.

---

## (b) How MemoryBench works

A TypeScript/Bun harness (MIT) with three pluggable interfaces (`MB/README.md:7-33`):

- **Benchmark** — `getQuestions()`, `getHaystackSessions(questionId)`, `getGroundTruth()`,
  `getQuestionTypes()` (`MB/src/benchmarks/README.md:7-16`).
- **Provider** — `initialize`, `ingest(sessions, {containerTag})`, `awaitIndexing`,
  `search(query, {containerTag, limit, threshold})`, `clear(containerTag)`
  (`MB/src/types/provider.ts:35-48`). `search()` returns `unknown[]`, which is JSON-stringified into the
  answer prompt unless the provider overrides the prompt (`MB/src/orchestrator/phases/answer.ts:49-68`).
- **Judge** — `evaluate()` returns `{score: 0|1, label, explanation}` (`MB/src/judges/README.md:6-15`).

**Pipeline.** Six phases run per question, each checkpointed to `data/runs/{runId}/checkpoint.json`
(`MB/README.md:115-126,162-169`): `INGEST → INDEX → SEARCH → ANSWER → EVALUATE → REPORT`.

- **Ingest** tags each question's data with `containerTag = "<questionId>-<runId>"`
  (`MB/src/orchestrator/phases/ingest.ts:44`) and waits 1 s between batches (`ingest.ts:9`).
  - **LoCoMo cost trap:** every question about a conversation carries that conversation's whole session
    list (`MB/src/benchmarks/locomo/index.ts:116-144`), and containers are per question. A conversation
    is therefore re-ingested once per question asked about it.
- **Answer** uses `gpt-4o` by default (`MB/src/utils/models.ts:230`). Context tokens are counted on the
  client (`MB/src/orchestrator/phases/answer.ts:70-176`).
- **Evaluate** makes two LLM calls per question
  (`MB/src/orchestrator/phases/evaluate.ts:11-111`):
  - a binary correctness judgment (`MB/src/judges/base.ts:9-52`). The judge prompt is per question type,
    and preference questions are graded against a rubric instead of a gold answer. If the judge's JSON
    doesn't parse, the harness looks for the words "correct" and "incorrect" in the text.
  - a relevance label for each of the top 10 results, from which it derives Hit@K, Precision, "Recall",
    MRR and NDCG (`MB/src/orchestrator/phases/retrieval-eval.ts:88-147`). "Recall@K" here really means
    "at least one hit": the dataset gives no size for the relevant set, and the NDCG ideal ranking is
    estimated from what was found (`retrieval-eval.ts:119-121`).
- **Report** gives accuracy overall and per question type, latency percentiles per phase, and
  **MemScore**. MemScore reports quality, latency and context tokens side by side and deliberately
  doesn't collapse them into one number (`MB/src/orchestrator/phases/report.ts:236-247`, `MB/README.md:128-160`).

**Datasets.** Each is downloaded at run time:

| Dataset | Source | Categories |
|---|---|---|
| LoCoMo | `snap-research/locomo`, `locomo10.json` (`MB/src/benchmarks/locomo/index.ts:13-15`) | single-hop, multi-hop, temporal, world-knowledge, adversarial (`:49-75`) |
| LongMemEval | HF `xiaowu0162/longmemeval-cleaned`, the `_s` split (`MB/src/benchmarks/longmemeval/index.ts:14-15`) | single-session-user / -assistant / -preference, multi-session, temporal-reasoning, knowledge-update (`:53-80`) |
| ConvoMem | HF `Salesforce/ConvoMem`, pre-mixed test cases (`MB/src/benchmarks/convomem/index.ts:13-14`) | user, assistant-facts, preference, changing, implicit-connection, abstention evidence (`:40-63`) |

`MB/framework.md:149-176` maps all three onto seven unified types for cross-dataset reporting:
FACT_RECALL, MULTI_HOP, TEMPORAL, INFERENCE, PREFERENCE, KNOWLEDGE_UPDATE and ABSTENTION.

**Adding a system** means implementing `Provider` in `src/providers/<name>/index.ts` and registering it
in three places (`MB/src/providers/README.md:19-32`). The repo also ships an onboarding skill
(`MB/skills/memorybench/skill.md`) that has an agent read a target codebase and generate the adapter.

**Cost shape (read from the code, not measured).** The two local baselines make one extraction call per
session at ingest. Every provider then costs one answer call and two judge calls per question. The
repo's own time estimate is 30–60 minutes for a full single-provider, single-benchmark run
(`MB/skills/memorybench/skill.md:110-115`). We didn't run it to check.

---

## (c) LongMemEval, LoCoMo and the rest: how they're built, and the pitfalls

**LongMemEval** (Wu et al., ICLR 2025; arXiv:2410.10813; https://github.com/xiaowu0162/LongMemEval):

- **Size:** 500 hand-curated questions over user–assistant chat histories.
- **Abilities tested:** five — information extraction, multi-session reasoning, knowledge updates,
  temporal reasoning, and abstention on false premises.
- **Haystacks:** `_S` is about 115k tokens and ~40 sessions per question. `_M` is about 500 sessions.
  Each question ships its own haystack and a question date.
- **Grading:** a GPT-4o judge per question type (`evaluate_qa.py`). Labelled evidence sessions and turns
  also allow retrieval to be scored separately from the final answer.
- **Headline finding:** assistants lose about 30% accuracy once the facts are spread across sessions.

This dataset is the closest match to Cicada's shape. It's the owner talking to agents over time, with
dated sessions and facts that change.

**LoCoMo** (Maharana et al., ACL 2024; https://github.com/snap-research/locomo):

- **Data:** the released `locomo10.json` has 10 conversations between two personas, 19–32 sessions each
  (counted 2026-09-24; the paper's abstract says "up to 35 sessions" and ~9K tokens on average,
  https://arxiv.org/abs/2402.17753).
- **Questions:** 1,986 QA pairs in five numeric categories (counted from the same file: 282 / 321 / 96 /
  841 / 446 for categories 1–5). Which number means single-hop, multi-hop, temporal or open-domain is
  not stated in the repo README, and harnesses disagree (see MemoryBench above); category 5 is
  adversarial.
- **Human ceiling:** about 88 F1 (secondary source, https://www.emergentmind.com/topics/locomo; not in
  the abstract).
- **Known problems:**
  - Zep measures the conversations at about 16–26k tokens, well inside a modern context window;
  - by Zep's reading of Mem0's own numbers, a **full-context baseline beats Mem0** (about 73% vs 68%)
    (https://blog.getzep.com/lies-damn-lies-statistics-is-mem0-really-sota-in-agent-memory/);
  - Zep reports category 5 unusable for missing ground truth (confirmed above: 444 of 446 have no
    `answer`), plus questions about image content absent from the descriptions and
    speaker-attribution errors;
  - a reported flaw in the reference scorer can grade a correct "I don't know" the same as a made-up
    answer (second-hand, not reproduced here).

**Others worth knowing:**

- **ConvoMem** (Pakhomov, Nijkamp, Xiong, arXiv:2511.10523, November 2025; the dataset is published as
  HF `Salesforce/ConvoMem`) has 75,336 QA pairs. Full context scores 70–82%, against 30–45% for
  RAG-based memory, on histories under ~150 conversations.
  RAG only becomes necessary past that point. For Cicada this means **a full-context control is
  mandatory**. At personal scale, "the memory system helps" has to be shown, not assumed.
- **BEAM** (ICLR 2026) has up to 10M tokens and 2,000 questions over 100 conversations. Framing it as
  the answer to LoCoMo and LongMemEval saturating is ours (inferred). The scale figures come only from
  Mem0's description at
  https://mem0.ai/blog/ai-memory-benchmarks-in-2026, which is a single source.
- **Zep/Graphiti** (arXiv:2501.13956) reports DMR and LongMemEval. It's architecturally the closest
  system to Cicada: a temporal knowledge graph whose facts carry `t_valid`/`t_invalid` plus
  created/expired times, a bi-temporal model (https://arxiv.org/html/2501.13956).
- **Letta's leaderboard** fixes the memory system and varies the answer model. It uses fictional facts
  so answers can't come from pretraining, a GPT-4.1 judge, and a penalty for unnecessary memory-tool
  calls.

**The pitfalls a Cicada pass must design around:**

| # | Pitfall | What the pass does about it |
|---|---|---|
| 1 | Different vendors use different judges and answer models, so their numbers don't compare (Mem0's own blog admits this) | The pass names both models. Every mode uses the same pair. |
| 2 | The answer model is a confound, which is exactly what Letta measures | The tools mode is run with at least two answer models. |
| 3 | A full-context baseline beats the memory system (LoCoMo) | A full-context control is a required row. |
| 4 | Vendor-run competitor baselines are under-tuned (Zep's dispute with Mem0) | No competitor rows. Cicada only, against its own controls. |
| 5 | The grader can't tell a correct abstention from a made-up answer | Abstention is reported as its own category, with a human-checked sample. |
| 6 | Bad items inside categories (LoCoMo's adversarial set) | Each category is reported separately. None is folded into a headline number. |
| 7 | Saturation | Numbers are read as a regression net and a mode comparison, not a leaderboard position. |
| 8 | Accuracy without its cost | Accuracy is always reported with context tokens and latency (as MemScore does). |
| 9 | Self-grading | The LLM judge is validated against human grades before it's trusted (the rule already in `benchmarks/README.md:57-58`). |
| 10 | Judge position bias and contamination | The judge prompt is fixed. LongMemEval's own gold answers are used. |

No benchmark we found varies **how retrieval is triggered** while holding retrieval, answer model and
judge fixed. G148's two modes do exactly that. It's the experiment the post implies but doesn't run.

---

## (d) Where Cicada stands on "tools versus hooks" today

| Surface | What triggers it | Depends on the chat model choosing to act? | Where |
|---|---|---|---|
| Capturing a Claude Code / Codex session | The harness's `Stop` hook, after every reply | **No** | `api/hooks/capture.py`; registered by `install.sh:312,318`; G105 |
| Chat exports, folders, browsers, Telegram, connectors, Wispr | The app or the backend | **No** | `api/routers/intake.py`, `api/services/episode_staging.py` |
| Consolidation, dedup, conflicts, decay, expiry | Sleep, on Cicada's configured engine | **No.** A weak chat model doesn't weaken extraction | `api/services/sleep_cycle.py:1012`, `api/services/engine_select.py` |
| Handshake (what Cicada is, the contract, the now-view) | MCP `initialize` → `instructions` | **No**, if the client puts `instructions` in context. Whether each harness does is G75's open question | `mcp/server.py:650`, `api/services/handshake.py` |
| The handshake for a client that drops `instructions` | Only the model calling `cicada_handshake`, which the skill tells it to do (`SKILL.md:18`). `HOOK_POINTER`, the line a `SessionStart` hook would inject, is defined and served as `hook_pointer` by `GET /handshake`, but nothing emits it | **Yes.** No `SessionStart` hook is registered (`install.sh:312,318` register `Stop` only), so this is still a tool call | `api/services/handshake.py:155-162`, `api/routers/state.py:148`; G76(b)(iv) |
| Recall: `cicada_recall`, `_recall_detail`, `_ask`, `_project`, `_timeline` | An MCP tool call | **Yes** | `mcp/server.py:177-` |
| Surfacing inbox questions: `cicada_check_nudges` | An MCP tool call, which the contract asks the model to make | **Yes** | `mcp/server.py:224` |
| Mid-session writes: `write_claim`, `note_progress`, `save_episode`, `add_source` | An MCP tool call | **Yes**, with a safety net: the Stop hook has already captured the words, so Sleep still extracts them. A missed write costs a delay until the next cycle, not the fact | `api/services/mcp_tools.py` (`note_progress` :967, `write_claim` :1120, `add_source` :1359, `save_episode` :2171) |

**The honest answer to the owner.** Cicada closed the hardest half first. Nothing is lost when a model
doesn't bother to save, because the harness saves and Sleep consolidates on its own engine. **Nothing
reaches the model unless it asks, beyond the handshake.** Recall and inbox questions stay tool-call
optional. Recall quality also depends on the model's judgment of *when* to look, which is
Letta's confound.

Even a hook can't remove every dependence on the model. With recall injected, the answer model still
has to *use* the block well. That's true of Supermemory's design too. What a hook removes is the
**silent skip**, the case where memory had the answer and no one asked.

---

## (e) The proposed Cicada benchmark pass (G148)

### What already exists, and a bug to fix first

`benchmarks/` is the thesis harness. It already has most of the pieces:

- a throwaway workspace scaffold with a name guard (`benchmarks/workspace.py:33-121`, `:87-100`);
- recall and a no-Sleep leg in the same process (`benchmarks/retrieval.py:45-60`: condition A is
  `handle_recall`, condition B is episodes only);
- a cheap `litellm` answerer (`benchmarks/answerer.py:26-50`);
- Sleep called in-process (`benchmarks/run_table3.py:213-239`).

**Verified bug, fix before anything reuses it.** Three runners pass a throwaway path as a keyword that
`Settings` silently drops:

- `benchmarks/run_table3.py:223` and `benchmarks/run_table1.py:90` call `Settings(memory_path=...)`;
- `benchmarks/run_ablation.py:96-101` does the same with extra thresholds.

Why the path is dropped:

- `memory_path` is a computed property (`api/config.py:38-41`);
- the real field `memory_root` accepts only its aliases `CICADA_MEMORY_PATH` and `CICADA_MEMORY_ROOT`
  (`api/config.py:33-36`);
- the model config ignores unknown keys (`api/config.py:261`).

Tested on 2026-09-24 with the memory environment variables unset:

- `Settings(memory_path=X)` and `Settings(memory_root=X)` both resolve to the default `~/cicada/memory`;
- only `Settings(CICADA_MEMORY_PATH=X)` or the environment variable reach `X`.

So `run_table3 --sleep-cycle-time` and every ablation row could run a real Sleep cycle, with commits,
against whatever bank the environment resolves — and the runners' bootstrap loads `api/.env` into the
environment first (`benchmarks/_bootstrap.py:8,42-43`), so on an installed machine that is the
configured bank (inferred from the code; `api/.env` was not read). That contradicts the harness's own promise
(`benchmarks/README.md:9-11`). The thesis runners also *read* the live `memory/` for questions
(`benchmarks/README.md:9`). The new pass does neither.

### Isolation: the owner's bank is never involved

- **One throwaway bank per unit.** A LoCoMo conversation is one unit, and all of its questions share
  one bank and one Sleep cycle. That's cheaper than MemoryBench's per-question containers and matches
  Cicada's model, where a bank is a life. For LongMemEval each question has its own haystack, so each
  question is a unit.
- **Its own `CICADA_HOME`** in a temp directory. Otherwise the connections prefs (`use_for_sleep`), the
  telemetry ledger, logos and the API token would come from the owner's real `~/.cicada`.
- **Environment, set per process:**
  - `CICADA_MEMORY_PATH=<workspace>`, through the environment and never the keyword;
  - `CICADA_TELEMETRY=off`, `CICADA_CAPTURE=off` and `CICADA_ALLOW_CONNECTOR_FETCH=off`;
  - `CICADA_ALLOW_FEED_FETCH` left unset.
- **A hard guard.** The runner refuses to start unless the resolved bank path is under a `cicada_bench_`
  temp directory (the rule `destroy_workspace` already uses). No server by default. If a mode needs
  HTTP, it runs a second `uvicorn` on a port other than 8000 with the same environment.
- **Results** go to `benchmark_results/`, which is gitignored (`.gitignore:23`). A committed write-up
  reports counts and scores only.

### The adapter: dataset → episodes

- **One session becomes one episode**, dated with the session's own date through
  `EpisodeDraft.timestamp` and `original_date` (the id's date), the stager every importer shares
  (`api/services/episode_staging.py:86-92,285-290`). `cicada_save_episode` always stamps "now"
  (`api/services/mcp_tools.py:2203`), and the Stop hook stamps the harness session's own start
  (`api/services/transcript_capture.py:294-298`), so neither can replay a dated dataset. Stage 1 then
  dates each claim's `valid_from` from its source episode (`api/services/entity_extractor.py:548`).
- **Turn times** go in the `turns: [{offset, ts, speaker}]` sidecar, so G118 spans cite real turns.
- **Speakers:**
  - LongMemEval is user–assistant, which maps directly onto `user:` and `assistant:`;
  - LoCoMo has two people. One is designated the synthetic owner and the other becomes `speaker:<label>:`.
    The runner records that choice.
- **The question date** from LongMemEval goes into the answer prompt. Cicada has no "as of date D"
  query. `/ask` and `handle_recall` read the current bank, so a cutoff is enforced by only ever
  ingesting sessions up to it.

### Sleep with a clock: the second blocker

`sleep_cycle.py:1330` calls `resolve_and_prune(...)` without `now`, so entity decay uses the wall clock
(`api/services/conflict_resolver.py:41,145`); the claim pipeline's reconcile/decay date defaults to
`date.today()` (`api/services/claim_pipeline.py:315`), and claim expiry runs against today
(`api/services/sleep_cycle.py:836`).

What that does, and does not, do to a 2023 dataset consolidated in 2026:

- **It does not archive everything on the first cycle.** Both decay paths cap the charge at
  `MAX_DECAY_DAYS_PER_CYCLE = 7` days per cycle (`conflict_resolver.py:33,195`,
  `claim_reconciler.py:73,699`), entity decay only touches pages that existed before the cycle and were
  not referenced in it (`conflict_resolver.py:146-159`), and claim decay never closes a claim
  (`claim_reconciler.py:711-713`). A one-cycle run on a fresh bank sees almost no decay.
- **It does skew anything that asks "as of when".** Claim expiry closes every claim whose stated end or
  `due` date is before 2026-09-24 on the first cycle (`claim_expiry.py:82`), `recorded_at` and the decay
  watermarks are stamped in 2026 (`claim_reconciler.py:124-128`), and a multi-cycle run accumulates up to
  7 days of decay per cycle regardless of the dataset's own gaps. Knowledge-update and temporal questions
  would then partly score the clock, not memory.

The functions already take a clock:

- `resolve_and_prune(now=)`;
- `reconcile_stage3(now_date=)` → `_decay_claims(..., today)` (`api/services/claim_reconciler.py:529-535,639,663-669`; `claim_pipeline.py:296,315`);
- `claim_expiry.expire(bank, today)`, which the demo bank already calls with a caller-supplied day
  (`api/services/demo_bank.py:101,116,126,677`).

**Build:** a benchmark-only override that sets Sleep's "now" to the unit's last session date, passed
down through one parameter. It's never an environment variable that production could pick up.

### The engine: the third blocker

A direct `sleep_cycle.run()` counts as user-triggered by default (`api/services/sleep_cycle.py:1012`).
Ruling 4 only protects *scheduled* cycles, and `engine_select.resolve_settings` may pick a plan engine
under `auto` (`sleep_cycle.py:1188-1199`). The runner therefore pins `llm_mode=byok` and a named cheap
model. The own-`CICADA_HOME` rule keeps the machine's `use_for_sleep` pref out. 💸 Every Sleep run in
this pass is paid API spend.

### Modes: every row holds the answer model and the judge fixed

| Mode | What reaches the answer model | What it answers |
|---|---|---|
| **H — hooks** | The runner calls recall on every question and puts the result in the prompt. Today that's `handle_recall`; once G149 ships it's the hook's own endpoint. This is MemoryBench's flow. | How good is Cicada's memory when it is always consulted? |
| **T — tools** | The model gets the handshake contract as its system prompt and `cicada_recall` / `cicada_ask` as tools. It decides. The runner logs whether and how often it called. | How much of H survives when the model chooses? The **tool-call rate** is a reported number. |
| **T × 2 models** | T with one small and one large answer model | The owner's question, measured: how much does "good and smart" matter? |
| **Full context** | The whole haystack in the prompt, no Cicada | The control. Does memory beat pasting everything in? |
| **No Sleep / Sleep** | H (and T) over raw episodes only (FTS and vectors, `retrieve_episodes_only`), then again after one Sleep cycle | What consolidation buys, by category. This is G101's "prove Sleep is still needed", measured. |

Two effects in Cicada's design will show up in the numbers, and the write-up should name them rather
than tune them away:

- **Promotion.** A fact said once in one short session may stay episode-only (the promotion rule), or be
  held in `pending_entities.jsonl` (PJ-0b). Single-hop recall then depends on the episode leg of recall.
- **Decay inside a long haystack.** Some decay is *correct* for knowledge-update questions, where the old
  value should lose.

### The first cheap pass

- **Pilot 1, no Sleep spend.** 30 LongMemEval_S questions, 5 from each of the six types, abstention
  included. Run H, T (two models) and full context, all in no-Sleep mode.
  - Cost: embeddings are local (EmbeddingGemma), so the only paid calls are 30 × (answer + judge) per
    row, plus the tool loop's extra turns. 💸 (small)
- **Pilot 2, one Sleep.** One LoCoMo conversation (19–32 sessions, one bank), run with and without
  Sleep in H and T.
  - Cost: Stage 1 makes one extraction call per episode chunk, so roughly 19–32 extraction calls
    (inferred: one chunk per session), plus
    Stage 2 disambiguation, plus answer and judge per question. 💸
  - Also time Stage 1+2, using `--episode-limit` first.
- **Scale only once both pilots are clean.** Add the remaining LoCoMo conversations and a larger
  LongMemEval_S slice. With Sleep, the 500-question `_S` set means 500 banks of about 40 sessions each.
  At one extraction call per session that's roughly 20k extraction calls (💸 real money, even on a cheap
  model), so the full set runs no-Sleep only unless the pilots justify it.

### What gets built first, in order

1. **Fix the `Settings` keyword bug** in the three runners and add the `cicada_bench_` guard.
2. **A clock override for Sleep's decay and expiry** in benchmark runs only.
3. **Dataset loaders** for LongMemEval_S (cleaned) and LoCoMo that produce dated `EpisodeDraft`s. Pin
   each dataset's file hash in the report.
4. **The engine pin:** `byok` plus a named model, own `CICADA_HOME`, refusing to run under `auto`.
5. **The tools-mode loop:** the handshake contract as the system prompt, the MCP tool schemas as
   functions, and per-question tool-call logging.
6. **The judge.** Reuse MemoryBench's per-type judge prompts (`MB/src/prompts/defaults.ts`) so
   categories compare. Before any number is trusted, a human grades a stratified sample of at least 50
   answers and the judge's agreement is reported.
7. **Later, optional:** a `cicada` provider inside MemoryBench, pointed at a benchmark-only backend, for a
   like-for-like row in their harness.

### How results are reported

- **Per category** (LongMemEval's six types, LoCoMo's five, and MemoryBench's unified types beside them),
  **per mode** (H, T × model with its tool-call rate, full context, no Sleep / Sleep).
- **Accuracy is always shown with its cost:** context tokens, p50/p95 latency, and paid calls per
  question.
- **Named models:** the answer model, the judge model, the Sleep model, the Cicada commit and the dataset
  hashes.
- **No single headline number, and no row set beside 85.9%.** A different harness, judge and dataset
  choice make that comparison meaningless.
- **Never against the owner's bank,** and no bank content in any committed file.

---

## (f) Implicit recall through harness hooks (G149)

Both harnesses expose the same mechanism.

- **Claude Code** (https://code.claude.com/docs/en/hooks.md, read 2026-09-24):
  - `SessionStart` matches `startup`, `resume`, `clear`, `compact` and `fork`. It can return
    `hookSpecificOutput.additionalContext`, and its plain stdout is also added as context.
  - `UserPromptSubmit` fires when a prompt is submitted, before Claude processes it. Its input includes
    `prompt` and `session_id`, it can return `additionalContext` (plain stdout is added too), and a
    command hook's default timeout is lowered to 30 s on this event. Exit code 2 blocks the prompt and
    erases it.
  - Context from a hook is capped at 10,000 characters.
- **Codex** (`github.com/openai/codex` at `c098f97`, main on 2026-09-24): its hooks engine has
  `codex-rs/hooks/src/events/user_prompt_submit.rs` and `.../session_start.rs`, and its output parser
  reads an `additional_context` field for both `SessionStartOutput` and `UserPromptSubmitOutput`
  (`codex-rs/hooks/src/engine/output_parser.rs:10-12,48-53`). Its tests reject an `additionalContext`
  that isn't a string and a `hookSpecificOutput` with no `hookEventName` (`output_parser.rs:532-545`), so
  the shape is `{"hookSpecificOutput":{"hookEventName":…,"additionalContext":"…"}}`, the same as Claude
  Code's. Not run hands-on.

One payload serves both, registered the same way the `Stop` hook already is (`api/hooks/registry.py`,
`~/.claude/settings.json` and `~/.codex/hooks.json`).

**A. SessionStart → the handshake, no tool call.** Emit the handshake text itself (≤ 1,800 tokens,
`handshake.load_or_build`, cached, no LLM) as `additionalContext`, rather than the one-line
`HOOK_POINTER` ("call `cicada_handshake`") that was drafted for this slot and is emitted nowhere today. It's G76(b)(iv)'s unshipped half and G131's question (a). G149 builds
it rather than reopening either row.

**B. UserPromptSubmit → a small, budgeted recall block.** The hook script is stdlib only and network
only, like `capture.py`. It posts the prompt to a new loopback endpoint that does the work on the server
(the name is open, e.g. `POST /recall/prompt-context`):

1. **Prefix first.** FTS over the prompt, the same engine-free path as `GET /search?mode=prefix`. That
   path never embeds and never loads the embedding model (`api/services/search_service.py:11-13`).
   Hybrid runs only when prefix finds something. It embeds the query on-device (EmbeddingGemma) and does
   a KNN lookup over stored vectors: no LLM call, but a model load on a cold process, which the latency
   cutoff below must absorb.
2. **A relevance floor.** Below it, the endpoint injects **nothing**. A miss costs zero tokens and adds
   no noise. This is the same rule as "surface only topic-relevant nudges".
3. **A budget.** About 400 tokens. Top pages as one line each with their current claims, plus any open
   inbox item on those entities (the `cicada_check_nudges(entity_ids=)` filter). The block says where it
   came from and names `cicada_recall_detail` for more depth.
4. **A latency cutoff.** The hook blocks the turn, so the script uses its own short client timeout
   (about 300 ms). On a timeout, an unreachable backend or any error it injects nothing and exits 0.
   It never exits 2, which would erase the person's prompt.
5. **The prompt is never logged or stored.** It isn't written by loguru, isn't in the access log (the
   G136 R22 rule, extended to this route), and isn't in telemetry. The ledger may hold one row per
   injection with ids and counts only: hit or miss, tokens, latency, entity ids.
6. **Skip conditions:**
   - `CICADA_CAPTURE=off` spawns, so Sleep's own `claude -p` is never fed its memory;
   - an active demo bank, so made-up memory never reaches a real session (the capture-side demo guard,
     mirrored);
   - an opt-out switch (`CICADA_RECALL=off`, plus a toggle in Settings → Agents).
7. **Registration and consent.** Through `api/hooks/registry.py`'s idempotent, marker-owned merge.
   `GET /agents/wiring` reports it next to auto-save, and the app installs it only after the person
   clicks, like the Stop hook (Track I T3/T7).

**What it doesn't change.** Writes stay tools, backed by Stop capture and Sleep. The contract's "recall
first" item stays, because the tools still give depth. Remote connectors (G135) are out of scope, since a
cloud app has no local hook.

**How we know it worked.** G148's H and T modes measure the ceiling that injection can reach, and how
much tools-only recall loses, per model. Running T with G149's block injected shows whether the block
closes the gap. The live ledger (hit rate, tokens and latency per injection) shows the cost on real use,
with counts only.

---

## Sources

- The post: x.com/DhravyaShah/status/2023630749065228364 (2026-02-17). It returned HTTP 402 to a fetch,
  so its claims and numbers are taken as relayed.
- MemoryBench: https://github.com/supermemoryai/memorybench at `94e2af54b661d90e77dddbd8fa4fa5b28c07a24e`.
- LongMemEval: https://arxiv.org/abs/2410.10813 · https://github.com/xiaowu0162/LongMemEval ·
  https://openreview.net/forum?id=pZiyCaVuti
- LoCoMo: https://github.com/snap-research/locomo · summary at https://www.emergentmind.com/topics/locomo
- Mem0: https://arxiv.org/abs/2504.19413 · https://mem0.ai/research ·
  https://mem0.ai/blog/ai-memory-benchmarks-in-2026
- Zep's critique of Mem0: https://blog.getzep.com/lies-damn-lies-statistics-is-mem0-really-sota-in-agent-memory/
  (a live dispute between vendors; Mem0's rebuttal wasn't checked line by line).
- Zep/Graphiti: https://arxiv.org/abs/2501.13956
- ConvoMem: https://arxiv.org/abs/2511.10523
- Letta leaderboard: https://www.letta.com/blog/letta-leaderboard/ ·
  https://github.com/letta-ai/letta/issues/3115
- Claude Code hooks: https://code.claude.com/docs/en/hooks.md · Codex hooks: https://github.com/openai/codex
  (`codex-rs/hooks/src/`).

**Not verified here:**

- the exact LongMemEval judge prompt;
- exact LongMemEval_S and ConvoMem question counts (LoCoMo's 1,986 was counted from the file);
- MemoryBench's published run configuration;
- a real MemoryBench run, because nothing was executed;
- whether MemoryBench's RAG baseline matches OpenClaw's actual memory;
- Codex's hook behaviour hands-on (read from source only).
