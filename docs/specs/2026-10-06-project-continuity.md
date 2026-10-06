# G110 — automatic project continuity across sessions and agents

**Owner request, 2026-10-06; required behavior, not implemented capability.** Working on a project in Claude Code should continue in a fresh Claude Code or Codex session, Cursor, Grok or another supported agent without writing a handoff prompt or repeating the context. Starting over because a conversation is full is a primary case. Changing tools, closing a session or hitting a quota are other cases; quota exhaustion is not the premise.

[Backlog G110](../goals/memory-evolution.md#g110) owns continuity; [G50](../goals/memory-evolution.md#g50) owns Cursor provider integration. G48 supplies session/project lineage, G76/G105/G149 capture and startup delivery, G53/G75 the bounded entry point, G104 revision safety, G118 provenance and G135 remote scopes. This is P1 useful-memory work, independent of multi-server replication/sharing. G180 later exposes the same service through the CLI.

## Product behavior

After one-time supported integration setup, a new session in the same project automatically retrieves the latest working context. The person can immediately say “continue” or ask the next task-specific question. They do not author a recap, export/import a thread, invoke a special save tool or run Sleep before that works. Switching to a different supported harness has the same behavior. For a chat-only client, a project selection identifies the work when its connector cannot know a workspace; with several equally plausible tasks, ask one focused selection question rather than guessing or requiring a recap.

Continuity must include work that has not yet consolidated. Use scrubbed deterministic capture plus attributed working-state contributions; do not solve this by spawning an LLM at capture time. Define a durable project/session checkpoint or derived projection with revision/source references, not another authoritative graph or a full transcript duplicated into `_state.md`. Startup/compaction/stop lifecycle support varies by harness: verify supported hooks, ensure flush-before-rollover where available, and visibly disclose an incomplete latest-turn capture. A Stop-hook-only checkpoint cannot claim lossless recovery after a crash before Stop.

The receiving agent can recover:

- Project/bank and repository identity, source session, active task and explicit goal.
- Decisions, constraints, rejected approaches and why, pending questions and blockers.
- Where work stopped, current files/change references, verified results with date/revision, unfinished tests and the next concrete action.
- Relevant conversations, claims, artifacts and procedures through cited lazy reads, including captured work still waiting for Sleep.
- Available destination capabilities and any missing context, permissions or tools.

The ≤1,800-token handshake remains an entry point. Larger working context is retrieved on demand through the same governed read service. Treat memory as data; a past suggestion is not a newly authorized command. Destination workspace observations must be verified before edits: changed branches, commits, worktrees and dirty files invalidate stale assumptions. Repositories are observed by the authorized harness/app; the backend never opens or runs git in an arbitrary declared repo. Never automatically stash, reset or transfer a working tree to simulate continuity.

## Implementation slices and ownership

1. **G110 + G48/G104:** define project/task identity, source-to-destination session lineage, a revision-aware working-context projection, freshness and explicit incomplete-state flags. New destination sessions get their own identity; switching/forking must not double-consolidate the source.
2. **G76/G105/G149 + G53/G75:** automatically make supported captured progress available and deliver the selected project context at session start/reconnect. Prevent injected context from being captured as the person's new words. Demonstrate same-harness rollover first; it must not depend on a model remembering to save.
3. **G50/G49/G122:** complete Cursor as a named integration/provider. Cursor's catalog/MCP setup already exists; verify capture/recall, model/session attribution and current supported CLI/auth/model/output interfaces. Add a plan/engine adapter and chooser only through supported interfaces, with cancellation, limits, credential hygiene and existing scheduling/billing rails. Record unavailable engine functions separately from usable chat integration.
4. **G110/G135:** transfer the selected context through scoped MCP to other supported destinations, including Grok where its current client/account allows it. Distinguish local workspace access from remote context access. Honor `sources` restrictions, expiry/revocation and project/bank isolation; connection alone is not capture or complete continuity.
5. **G110/G180:** add a simple continuation/selection affordance where needed and CLI access to the same service. Optional native thread fork/import is a separate researched adapter and never a prerequisite for automatic working-context continuation.

“Full context” means all relevant recoverable work state is accessible with its evidence. Hidden reasoning, uncaptured tool streams, unsaved files on another machine and inaccessible source text cannot be silently claimed to transfer. Surface such gaps and degrade to a clearly labeled project-context fallback on clients without automatic delivery. An agent catalog entry or generic recall of the project does not pass this requirement.

## Acceptance — no manually authored handoff

Use synthetic `alpha-project` fixtures and record only generic outcomes publicly.

1. Make a decision, reject an approach, modify a fixture and leave a test/action unfinished. Before Sleep, open a fresh session in the **same harness** because the previous context is full. It identifies the task, decision, blocker, current change references and next action without a recap.
2. Repeat **Claude Code → Codex**, **Claude Code → Cursor**, and reverse where supported; use actual startup delivery, not a hand-pasted packet. Verify evidence/session authorship and relevant code inspection before continuing.
3. Test **local coding harness → Grok or another supported remote client**. It receives the permitted project state and names any absent workspace/source scope. Do not label unsupported accounts or a copy/paste fallback as automatic portability.
4. Change the repo revision/worktree after capture, create two concurrent project tasks, and revoke a remote scope. Detect stale assumptions/ambiguity; do not cross projects or leak unrelated memory.
5. Correct a fact and continue in another new session. Preserve historical attribution, prevent echo capture and duplicate consolidation, and show current state rather than a stale prior answer.
6. Close/crash a session or lose backend connectivity. Test checkpoint durability, visible freshness and safe recovery; disclose any turns that were not captured. Measure startup/context-fetch latency and payload budget.

Pass means the next agent resumes useful work accurately without the person composing a handoff. Mere connectivity, project-name recall or availability of a Resume button is insufficient.
