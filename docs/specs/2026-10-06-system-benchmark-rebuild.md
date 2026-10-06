# G148 — Rebuild benchmarks for the whole Cicada system

**Owner direction, 2026-10-06:** the current benchmarks are inadequate and should be redone from scratch. The main interest is performance of the whole system, including running consolidation, rather than a retrieval-only leaderboard. [G148](../goals/memory-evolution.md#g148) owns the replacement harness and protocol; this supersedes its earlier “triggered research only” priority and adapter-only framing. P1, after applicable P0 integrity fixes, alongside the first-memory trial; building the full harness does not gate a small hands-on trial.

## Why a new harness

The existing scripts are historical experiments, not acceptance evidence for today's complete system:

- [answerer.py](../../benchmarks/answerer.py) calls LiteLLM directly, outside Cicada's subscription-engine routing.
- [run_retrieval_eval.py](../../benchmarks/run_retrieval_eval.py) launches Claude for answers and resolves its judge separately. A named answer model does not pin the whole run to that model/provider.
- [_bootstrap.py](../../benchmarks/_bootstrap.py) imports the developer API environment and defaults a live-memory path. The new harness needs isolated, explicit configuration.
- [run_table3.py](../../benchmarks/run_table3.py) does offer static/recall metrics and an optional Sleep timing pass. That useful slice does not establish ingestion-to-consolidation-to-answer quality, resource use, revision behavior or recovery.

Preserve dated outputs as legacy and label their scope. Design the replacement independently; reuse a fixture or helper only after validating it against the new contract. No rewrite or benchmark execution has occurred in this documentation change.

## Primary benchmark: intake → Sleep → useful answers

Exercise production entry points and the real five-stage drain, engine-independent tail, commits and derived-index updates. Stage bypasses and precomputed gold summaries are separate diagnostic runs, never a whole-system result.

| Scenario | Required behavior and measurements |
|---|---|
| Fresh dated conversations | Ingest raw turns, consolidate, inspect entities/claims/evidence and ask held-out questions. Report useful answer quality as well as time/resources. |
| Continued and revised threads | Repeat unchanged input, append turns, correct/remove facts and consolidate again. Measure repeated work, latest-state retention, stale/duplicate claims and evidence validity. Compare G104 strategies later against the unchanged full-thread baseline. |
| Multiple sources | Add a document, permitted source-check result and supplied video-watch record through their production staging paths. Test cross-source relations, source versus evidence semantics and whether video content survives Sleep. Add iMessage fixtures when G179 ships. |
| Temporal changes and contradictions | Fix the evaluation clock, advance it deliberately, preserve historical versus current facts, apply a human correction and inspect unresolved conflicts, decay and nudges. Never let today's date silently decay a historical dataset. |
| Pause, cancellation, failure and resume | Interrupt between/within batches, simulate a plan limit or failed engine call, continue the drain and verify processed flags, checkpoints, source revision checks, owned commits and no lost/duplicated work. |
| Increasing bank size and concurrent activity | Use declared small/medium/large fixtures; measure drain throughput and API/recall responsiveness during Sleep, indexing and concurrent permitted capture/writes. App responsiveness is a separate real-app track, not inferred from backend timing. |

Performance means both **what the system learned** and **what it took to learn it**:

- **Quality:** grounded correctness, temporal updates, relationship/cross-source questions, abstention, irrelevant-memory avoidance, duplicates, attribution and inspectable evidence; ability to answer useful ordinary questions after consolidation and in a fresh session.
- **Operational behavior:** wall time per stage/batch/full drain, episodes/turns or input bytes processed per unit time, model calls/retries and reported tokens, embedding/index time, CPU time, peak memory, disk/index growth and measured API/recall latency distributions. State sample count, warm/cold conditions and measurement method; separate queue/provider waiting from local processing.
- **Integrity/recovery:** correct retirement and requeue, continuation/source revisions, commit scope/author, no lost claims, repeat-import idempotence, recoverable checkpoints and observable failures. A faster run that loses memory fails acceptance.
- **Usage:** actual provider-reported usage when available, unavailable fields explicitly unknown, and subscription limits/pauses distinct from metered cost. Do not convert plan usage into an invented per-run dollar bill.

## Controls and grading

Keep the same questions, answer model/effort, tool/context budgets and source corpus across controls:

1. **Full-context model:** raw conversation supplied directly, showing answerability when all evidence is available.
2. **Cicada before Sleep:** production recall over staged raw episodes.
3. **Cicada after Sleep:** production recall/agent tools after actual consolidation, with all consolidation time and calls included in the report.

Record the exact exposed surfaces and prompts. Keep expected answers/evidence and judge output out of ingestion, the bank, answer prompts and subsequent capture. Fresh answer sessions are isolated from previous questions. Judge calls count separately; manual grading is supported. If Luna also grades Luna, disclose that and manually audit disagreements/errors before trusting automated scores. Do not treat word overlap or substring presence as grounded correctness.

## First subscription-only pilot

Support user-started Codex execution authenticated with ChatGPT, with one explicit model/effort pin for **every generative stage**, including disambiguation, patterns/nudges, answers and any optional judge. The owner's requested starting target is `gpt-6-luna`; verify account/client availability at execution. Use the existing guarded subscription adapter and local embeddings, no inherited API-key fallback, automatic top-up, provider substitution or quota retry loop. Record actual limits rather than promising a full run will fit the $100 plan. A scheduled run still cannot use a subscription plan (binding ruling 4).

Start with deterministic synthetic scenarios for revisions, grounding and recovery, then **one LoCoMo conversation, consolidated once, with 30 fixed questions** across useful categories and the three controls. Preserve speakers and session timestamps. Record dataset commit/hash, selection rule and excluded/ungradable items; handle adversarial items separately rather than inventing missing gold answers. This is a subset pilot, not a full-dataset leaderboard score. LongMemEval_S follows for harder knowledge-update, temporal and abstention cases; its separate history per question makes whole-Sleep evaluation substantially larger. Public datasets are fixtures, not a substitute for G10's private hands-on usefulness trial.

## Deliverables and completion

1. A new documented runner with a small preset, explicit bank/home/config/model/clock, isolation guards and repeatable dataset/fixture loading. Never default to or mutate a live bank; benchmark agent sessions and judge text must not leak into real capture.
2. Stage instrumentation and structured run manifests/results: code revision, hardware/OS, engine/auth kind without secrets, models/effort, local embedding model/index state, dataset hashes, clock, settings, controls, failures and resume lineage. Private traces remain local; public reports use synthetic or public dataset facts only.
3. A completed small whole-system pilot with saved generic results, error diagnoses and a documented subscription-only command. No claim of success based only on a runner existing, mocked Sleep, or older scores.
4. Scale and failure/recovery reports after the pilot works. Use observations to prioritize G104/G171/G183 and source/video/provider improvements; change models only in a separately reported comparison.
5. Archive or retire superseded runners/documentation after reproducing the required coverage. Keep historical results labeled; ensure the supported benchmark entry point has no hidden API judge or dependency on the author's private bank.

Related: [G10](../goals/memory-evolution.md#g10), [G104](../goals/memory-evolution.md#g104), G118/G147/G163/G171/G177/G183, [provider/ingestion modularity](2026-10-06-provider-and-ingestion-modularity.md), G22/G162 and the [earlier benchmark research](../research/2026-09-24-memory-benchmarks-and-implicit-recall.md). No model calls or bank reads were authorized or performed by writing this brief.
