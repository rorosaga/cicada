# G104 — Incremental consolidation of resumed conversations

**Owner follow-up, 2026-10-06. Research brief, not a settled algorithm or implemented optimization.** Re-extracting the entire captured conversation every time it grows is unlikely to be efficient for frequently consolidated long threads. Investigate continuation-aware consolidation while preserving the ability to revise earlier conclusions in light of later context.

[G104](../goals/memory-evolution.md#g104) owns both revision correctness and this efficiency investigation; no duplicate work ID. **P0:** demonstrated source-revision/integrity defects. **P1 RESEARCH:** measure and choose incremental processing. The optimization does not block G10's small baseline trial. G110 needs fresh working context before Sleep, G118 needs stable evidence, G163 owns durable reading/retry reuse, and G171's incremental indexes do not implement incremental extraction.

## Verified current behavior

Checked merged `dev` at `ba7a4957`, without reading a private bank or running a model:

- `transcript_capture.py:376–394` hashes the scrubbed captured body. If it changes, the same episode is rewritten and marked `processed: false`. An unchanged captured body is skipped.
- `sleep_cycle.py:2640–2670` selects unprocessed episodes and supplies their whole captured body; `entity_extractor.py` chunks that content for extraction. There is no committed turn/chunk checkpoint that selects only a new suffix.
- `episode_staging.update_in_place` does the equivalent for changed source-keyed exports. “Delta import” means new/grown/unchanged conversations, not a turn-level extraction delta inside a grown thread.
- `sleep_cycle._mark_episodes_processed` rechecks the selected body revision under the episode lock. A newer capture remains waiting for a later run. This prevents retiring unseen content; it does not avoid rereading an earlier prefix.
- `transcript_extract.py:54–61` caps each turn at 2,000 characters and keeps a head-stable 100,000-character session. Later content can be dropped and flagged; additional turns may leave the captured body hash unchanged once the cap is exhausted. This limits any claim that ongoing progress or full context is preserved.

Evidence: [capture writer](../../api/services/transcript_capture.py), [source-keyed staging](../../api/services/episode_staging.py), [Sleep selector/retirement](../../api/services/sleep_cycle.py), [extractor](../../api/services/entity_extractor.py), [capture limits](../../api/services/transcript_extract.py), [existing capture test](../../api/tests/test_capture_transcript.py).

Stop capture is deterministic file I/O, not an LLM call. Repeated model extraction happens when Sleep subsequently processes the changed episode; don't equate every hook firing with another paid consolidation.

## Efficiency judgment and options to compare

Let captured length grow by equal increments, with a consolidation after each increment. Re-reading each complete prefix makes total extraction input grow with the sum of those prefix lengths. That can be quadratic in the number of checkpoints, compared with linear unique content. This is an illustrative scaling argument, not a measured bill: chunk overlaps, prompts, caching, context reads and later stages affect actual tokens, calls, latency and cost.

Compare these strategies against today's full-reprocessing baseline:

1. **Appended turns plus bounded prior context.** Prove that the normalized captured prefix is unchanged, process the new suffix with a small overlap and relevant committed claims/project state. Resolve pronouns and corrections without blindly treating the continuation as a standalone conversation.
2. **Stable chunk/turn checkpoints.** Reuse accepted extraction for unchanged source units; invalidate edited units and necessary dependents. Avoid shifts in arbitrary chunk boundaries invalidating the whole thread. Compare per-turn versus chunk cost/complexity and offset fidelity.
3. **Targeted reprocessing with full fallback.** An edit, deletion, reordering, compaction or late correction can affect earlier conclusions. Reprocess affected sections/claims and fall back to a full captured revision when the change cannot be bounded safely. A keyword heuristic alone is not proof that earlier meaning is unchanged.
4. **Existing full reprocessing with scheduling/cache improvements.** It may remain the simplest safe option for short or rarely revisited threads. Measure before introducing persistent checkpoint complexity; fewer runs or durable G163 reuse must not hide new progress.

**Working hypothesis:** append-only delta plus bounded prior context, with revision-aware invalidation/fallback. Select only after comparing useful recall, contradictions, evidence integrity and measured overhead. Do not impose an arbitrary “reconsolidate at most once” cap that makes later contributions ineligible.

## Correctness requirements before implementation

- Keep one logical conversation identity and existing promotion semantics. More continuations/chunks are not more independent conversations or more trust. Do not inflate reference frequency by rereading the same observations.
- A checkpoint means successfully reconciled and committed input, not merely “a model answered.” Advance it only with the owned-path commit; cancellation, plan pause, failures and crashes must leave safe retry work. Coordinate with G163's reading journal without conflating retry caching with continuation processing.
- Use source revisions/content hashes and stable turn/chunk identity, not only timestamps, lengths or a `processed` flag. Include extractor/prompt/schema dependencies in cache invalidation; old accepted results must not silently survive an incompatible extraction change.
- Map any suffix-local offsets back to the canonical source revision. Evidence keeps exact offsets and hashes, original speaker/model attribution and historical validity; preserve the current exact-locate/no-fuzzy rail. Decide how old source revisions are located after edits rather than overwriting their meaning.
- Reconcile revised support per claim, including multiple independent sources. Removing an assertion from an edited export is not proof that the real-world fact became false. A later correction can warrant invalidation or a conflict; never blindly delete every claim from a session or close the person's belief with an agent verdict.
- Handle concurrent capture using the current revision-safe retirement. Processing one selected revision must not consume a new append that arrives mid-run. Preserve single-writer/page-lock/commit attribution rails.
- Investigate capture-cap visibility and retention before claiming lossless continuation. Do not silently drop the prefix to keep the tail and break earlier spans; evaluate stable bounded/segmented capture only within the one-conversation and provenance rails. No unlimited capture, tools/code retention or LLM at capture is implied. G110 must show freshness and missing context.
- Checkpoint/cache metadata must be portable or safely rebuildable from Markdown/git. No second authoritative fact store, query logging, transcript scanning outside permitted capture, or private text in telemetry/public reports.

## Research cases and decision record

Use synthetic conversations only for the initial investigation:

- Several append/consolidate rounds, plus repeated unchanged capture; verify earlier extraction is reused where eligible and no observations/claims are duplicated.
- A short continuation referring back to an earlier entity; a changed preference or corrected earlier assertion; a fact with independent supporting evidence.
- An edit, removed turn, reordered export, changed scrubbed prefix, compaction, and an oversized thread crossing each capture cap.
- Capture during extraction/commit, pause/cancel/restart before commit, corrupted checkpoint and model/prompt/schema changes.
- Full baseline versus each candidate: processed input/estimated or reported tokens, repeated-prefix fraction, invocation counts, end-to-end time, checkpoint/storage overhead, retrieval usefulness, missed corrections, wrong supersessions and evidence-locator failures. Clearly separate extraction from later-stage cost and model-reported usage from estimates.

Deliver a dated recommendation, explicit source-revision semantics, checkpoint/invalidation design, reproducible synthetic cases, measurements and remaining uncertainty. No invented savings target or benchmark claim. Functional/static probes can start without model spend; meaningful semantic comparisons need an explicitly chosen engine and budget at execution time. A real-memory comparison belongs in the owner-approved trial with only generic outcomes public.

No consolidation, benchmark, paid call or feature implementation was performed while recording this brief.
