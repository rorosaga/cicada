# G10 — first hands-on memory trial

**Prepared 2026-10-06; not executed.** This is the next user-driven product test, before a formal G148 benchmark. It does not authorize reading a private bank, choosing paid spend, publishing data or resetting processed history during the backlog review. [Priorities](TODO.md) · [G10 reasoning](memory-evolution.md#g10)

## Before the run

1. Close relevant G183/G177 integrity gaps before combining capture, agent writes and Sleep. Reproduce/fix G185 separately; determine whether it is only usage display or indicates a consolidation defect. Confirm current tests on the intended execution revision.
2. Choose a separate named **real** trial bank, or explicitly choose the existing bank with a recoverable committed baseline. Do not use a demo bank for private imports. Confirm the app, backend, hooks and clients all point at the intended bank; avoid a bank switch while writes are in flight.
3. Choose the consolidation engine and limit: user-started plan use is allowed; API use needs a budget. Verify engine readiness without starting a run. Do not enable scheduled plan use or continue-after-reset automatically.
4. Keep the bank’s current embedding model. Check index health and recorded model/dimension choices; rebuild only a damaged disposable index through supported maintenance. Never erase model metadata or silently switch/re-embed. A model download/upgrade is a separate choice.
5. Select the current ChatGPT and Claude exports via the supported import UI/path. Read the preview’s new/grown/unchanged counts and date/source handling. Delta import is already implemented; do not delete the old bank or force all episodes unprocessed. G170 owns attachment/speaker correctness; G104 owns resumed-session semantic revision.

## Run and observe

Start with a representative small batch so import attribution, entities, evidence and questions can be inspected before a long drain. Check G169’s owner page and G170’s quoted-document/source attribution. If those pass, run the user-started drain over the selected queue. Observe G171 progress/pause/resume, responsiveness and duplicate decay questions; avoid unrelated writes until applicable locking fixes are verified.

Review several outcomes privately: does it remember a useful detail, connect a prior decision to the present, preserve the reason something was rejected, understand a changed preference and show a source? The owner chooses the real questions; do not put their words, claim text, names or answers into this public repo.

| Check | What useful behavior looks like | If it fails |
|---|---|---|
| Literal and paraphrased recall | Same relevant memory is found both ways | Compare lexical hits, semantic hits and final agent answer before blaming the embedding model. |
| Fresh session / context rollover | Same project resumes in a new session before Sleep, without a handoff prompt or recap | G110/G48/G76/G149: distinguish current working-state capture/startup delivery from general project recall. |
| Different agent | Claude Code → Codex/Cursor, and supported remote client, recovers decisions, current changes, blockers and next action | G110/G50/G135: verify lineage, workspace freshness and scopes; unsupported delivery or a hand-pasted packet does not pass automatic portability. |
| Resumed conversation | After a first batch, append new turns, include a correction, then verify current facts and exact evidence after the next run | G104: current baseline re-extracts the whole captured thread. Record repeated-input/usage where available; incremental research does not gate this test. |
| Correction | Current belief wins; earlier state remains historical | Inspect claim validity/supersession (G104/G118), not just prose wording. |
| Provenance | The agent can show when/where it learned a fact | Verify evidence locators, attribution and source permission (G118/G116/G135). |
| Missing evidence | It admits the gap instead of inventing a memory | Separate retrieval misses from ungrounded answering (G52/G93). |
| Unrelated prompt | It does not inject irrelevant personal context | Review recall floor/routing and relevance (G149/G93). |
| Decision/action | Recalled context changes a useful recommendation or action | Judge utility and applicability, not merely whether an entity exists. |
| Start prompt | A saved candidate is found by objective, adapted for a different synthetic project/model and reused with original/variant provenance | G73 acceptance; distinguish untested candidates from successful-use evidence. No Sleep or skill compiler required for save/copy. |
| Procedure | New session reuses a validated synthetic query/script | G55/G112 acceptance; no live SQL execution merely because a file was saved. |

## Source and video checks — separate from the export batch

The [source/video code-path review](../research/2026-10-06-source-refresh-and-video-gaps.md)
distinguishes implemented paths from proposed work. Add a source on a chosen
entity privately, assign its real predicate and inspect how it is exposed to the
agent. Where a pending checkable item exists, try the current permissioned
shadow-check path; the finding must not silently change a belief. Without an
inbox item, record the missing ordinary-query refresh path as a G61 gap rather
than creating a fake conflict just to make the tool accept it. Observe whether
“site confirmed” and “fact checked” are clearly distinguished.

Use one allowed video with the existing agent handoff. Check the reported
transcript/frame basis, timed excerpts and creator attribution, then consolidate
the new watch episode and ask a topic/project question whose answer needs its
content. Saving a URL alone does not produce a watch record; queue completion
is not Sleep completion. Missing timestamp navigation, acquisition or relevance
is a specific G22/G162 failure. Optional API watching and model changes are not
prerequisites to this trial. Keep personal URLs, content and questions private.

## Try the clients separately

Start with Claude Code and Codex, where deterministic capture and implicit recall already exist. Include Cursor through the existing catalog setup and the G50/G76 integration work; test same-harness rollover and cross-agent continuation against [G110’s acceptance](../specs/2026-10-06-project-continuity.md) without a handoff prompt and before Sleep. Then verify current connector support/setup for Grok, ChatGPT Desktop, Claude Desktop and each chosen iPhone app/account. Record unavailable support honestly; query connectivity is not automatic capture. Keep remote source scopes restrictive and explicitly test revocation and cross-bank isolation. Read the current official client documentation when executing; app capabilities change.

## Decide the next change from the failure

Record only date, revision, client, model/engine identifiers, generic check, pass/fail and failure category publicly. Keep personal questions/answers and screenshots private. Prefer a short private reflection on “did this make the conversation better?” over a benchmark score. Route concrete failures to their existing G rows: capture/import, consolidation, recall, answer grounding, provenance/permissions or UI. Change embedding models only if observed semantic failures justify the comparison. G148’s controlled benchmark follows when it answers a concrete question.

## G104 efficiency follow-up

[Continuation-aware consolidation research](../research/2026-10-06-incremental-consolidation.md) now compares repeated full-thread input against bounded delta/reuse strategies. Keep this first trial as the baseline; do not reset processed history or implement a new checkpoint just to run it. Record generic prefix/revision/capture-cap observations and usage basis. Any semantic comparison/model spend needs the selected engine/budget at execution time. A thread beyond current capture limits may have missing later turns; test that first with synthetic input, and keep G110 context-freshness claims honest.
