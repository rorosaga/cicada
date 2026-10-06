# Agent Memory Repo: interoperability and a leaner agent interface

**Date:** 2026-10-06 · **Status:** documented proposals; no implementation or benchmark run.
**Backlog:** G186 (AMR export/import), G180 (CLI + leaner MCP), G76 (continuity demo),
G55/G112 (procedures + portable skills), G16 (shared memory, parked), G132/G181 (backup),
G148 (comparison benchmark). Permanent task addresses live in
[`memory-evolution.md`](../goals/memory-evolution.md); execution state lives in [`TODO.md`](../goals/TODO.md).

The owner asked to preserve the comparison with Cognition's release, incorporate the useful parts
of a supplied Claude analysis, and document the desire for a leaner MCP. This is a research note,
not an implementation plan or permission to run procedures, publish memory, or change bank formats.

## Evidence and scope

External repository inspected at
[`1db04a5735adbc4f2158308f2077fd960e243c04`](https://github.com/AgentMemoryRepo/agentmemoryrepo/tree/1db04a5735adbc4f2158308f2077fd960e243c04):

- [README](https://github.com/AgentMemoryRepo/agentmemoryrepo/blob/1db04a5735adbc4f2158308f2077fd960e243c04/README.md): memory loop, Dreaming, composition, reusable SQL example, installation trial.
- [SPEC](https://github.com/AgentMemoryRepo/agentmemoryrepo/blob/1db04a5735adbc4f2158308f2077fd960e243c04/SPEC.md): required root `MEMORY.md`, root-relative links, one-line entries and optional metadata.
- [Skill](https://github.com/AgentMemoryRepo/agentmemoryrepo/blob/1db04a5735adbc4f2158308f2077fd960e243c04/skills/agent-memory-repo/SKILL.md): invoked local-repo workflow, clean-tree guard, explicit private-remote setup, no automatic startup or scheduled jobs.
- A Devin plugin manifest and MIT license complete the five tracked files. There is no runtime,
  hook or consolidation implementation in this public snapshot. The
  [Cognition page](https://cognition.com/agent-memory-repo) describes a broader operating model;
  this inspection says nothing about unpublished Devin functionality or installation success.

Cicada anchors below are relative to this repo at `934711c9`. Only public source and docs were read;
no runtime bank, personal settings or harness transcripts were inspected. Statements in the supplied
analysis about a particular bank's empty `_procedures/` directory were not verified or retained.

## What the comparison establishes

Both use git, Markdown, linked pages, a short session entry point, and periodic consolidation as a
design. Cicada implements a much larger lifecycle; AMR specifies a minimal format and skill that
ordinary filesystem-capable agents can understand. The useful question is which parts Cicada
should speak and make easier to access. More machinery does not establish better memory accuracy.

| Area | Current Cicada evidence | Assessment against the public AMR release |
|---|---|---|
| Capture | `api/services/transcript_capture.py:295`; `docs/architecture/capture-and-sleep.md:32` | Hook-driven capture and one episode per resumed session avoid reliance on agent-selected saves. AMR's released skill is invoked. |
| Recall | `api/services/hook_recall.py:1`; `api/services/search_service.py:312` | Startup/prompt hooks plus lexical, vector and current-claim retrieval are implemented. Hook recall is bounded and name-triggered, not unrestricted semantic recall. |
| Time and provenance | `api/services/claims.py:124`; `api/services/evidence.py:469` | World-valid dates, recording dates, supersession, observer/trust, and hashed evidence spans are richer than optional session/date metadata. |
| Forgetting | `docs/architecture/capture-and-sleep.md:251` | Decay classes, spaced mentions, import protection and archives are implemented. AMR describes cleanup but supplies no clock or cleanup runtime. |
| Human authority | `api/services/conflict_resolver.py:152`; `api/services/check_record.py:16`; `api/services/inbox_service.py:774` | Unresolved conflicts can reach the person; S3 checks report findings without settling beliefs; verdicts are recorded. AMR's described loop delegates cleanup and contradiction handling to an agent. |
| Secrets | `api/services/episode_scrub.py:1` | Cicada has shared code for scrubbing supported secret patterns. AMR provides an instruction not to save secrets. Scrubbing is not a guarantee that all sensitive material is detected. |
| Concurrency | `docs/architecture/storage.md:544` | Git/page locks and semantic claim reconciliation address more than text merging. Coverage is incomplete: Sleep's page writes and some inbox resolvers remain outside the page lock. |
| Breadth | `docs/architecture/capture-and-sleep.md:11` | Cicada implements multiple capture channels. AMR allows arbitrary files and agent-saved knowledge; its public skill does not implement comparable ingestion adapters. |

No separate work is needed merely to rediscover memory-as-data, a short entry point, or scoped
staging: `api/services/handshake.py:100,288`, `:69` (1,800-token chars/4 budget), and
`api/services/git_service.py:538` already cover those ideas. Retain and verify them when interfaces change.

## 1. Leaner MCP and CLI-first shell agents — G180

**Owner direction:** make the MCP leaner alongside the already-prioritized CLI. MCP remains a
supported interface for clients without a shell and for scoped remote access.

**Measured baseline, 2026-10-06:** static extraction of `mcp/server.py`'s `TOOLS` assignment
(`:179`, returned by `tools/list` at `:879`) yields **30 tools**, **35,109 characters** with
Python's default `json.dumps`, or **33,772 characters** in compact JSON with `ensure_ascii=False`.
35,109 / 4 gives **8,777 estimated tokens**; this is a serialization-based proxy, not a tokenizer
count or a measured client context charge. Hosts differ in loading and discovery behavior.

Implementation tasks to carry in G180:

1. Ship the CLI over the same service layer, with discoverable `--help`, structured `--json`, and
   existing provenance/locking/refusal behavior. Resolve its HTTP-vs-in-process write path first.
2. Teach shell agents the CLI through the skill; keep MCP instructions for other clients. Hooks
   continue to provide capture and recall independently of tool choice.
3. Audit descriptions for repeated traversal policy and examples. Keep each tool's job, arguments,
   consequential refusals and constraints visible; move shared workflow guidance into the existing
   handshake/skill without creating a second contract. R12 still binds.
4. Evaluate grouping closely related operations and optional tool profiles. Do not choose a fixed
   reduced tool count before checking representative client workflows. Existing tool names need a
   compatibility/migration story if changed.
5. Preserve remote capability boundaries (`api/remote/catalog.py:35`), `sources` protection,
   authorship, and withdrawal ownership. A generic dispatcher must not let read authorization reach
   writes, or let record authorization resolve human questions. Fewer tools is not sufficient by itself.
6. Record before/after schema sizes, handshake/skill overhead, discovery calls, task completion and
   tool-selection mistakes for recall/detail, save/claim, inbox, and reading/video workflows. Validate
   schema/primer parity and scope refusals. Measure total task overhead, not just `tools/list` size.

## 2. Speak AMR through a generated export — G186

**APPLY proposal:** an export outside the bank, with a candidate CLI spelling
`cicada export --amr <dir>` (not an existing command). No authoritative `MEMORY.md` is added to a
live bank; `_state.md` remains a cursor. A bank archive and an interoperable projection are different
artifacts: this export is intentionally lossy, not a substitute for full backup.

Implementation tasks:

- Generate a bounded root `MEMORY.md` with links to topic/entity files and selected standing context.
- Translate bare entity-id links to paths from the export root, such as `[[entities/alpha-project]]`;
  validate every emitted link and any linked evidence/artifact file. Never follow symlinks outside the bank.
- Project current claims into one-line bullets with metadata. Preserve attribution and distinguish
  inferred claims from the person's words. `added` represents when Cicada recorded the claim, not its
  world-valid date; represent validity separately where relevant. Source references must remain usable
  in the export, without leaking local machine paths. Do not invent missing sources or exact evidence.
- Define selection and disclosure before copying raw episodes: a useful default should not silently
  export every conversation. Keep private data out of this public research note and test fixtures.
- Produce a deterministic snapshot with source-commit provenance and an explicit stale-snapshot notice.
  Use a consistent committed view; do not mutate the active bank, its cursor, indexes or git history.
- Export to a new/empty destination by default; define repeat-export ownership before allowing updates
  so regeneration cannot overwrite files an agent or person added. Do not configure or push a remote.
- Acceptance: a filesystem-only agent using the AMR skill can navigate the export and answer a synthetic
  preference/current-fact question without Cicada or MCP installed. Bank hashes/history remain unchanged;
  missing evidence and stale/closed beliefs are represented honestly.

**RESEARCH companion:** ingest an AMR repo as an external source through the existing source-agnostic
pipeline. It is not automatically cheap or lossless: entry/date parsing, ownership, edits, removals,
links and artifact handling need a contract. External bullets remain attributed external/agent data,
not owner statements by default. Parse bytes; do not execute referenced scripts, follow arbitrary
paths, or honor embedded instructions. Reuse scrub/staging rules and test repeated imports with synthetic
data. G186 tracks this exploration separately from the APPLY export.

## 3. Preserve reusable procedures, then export skills — G55 / G112

Use the public SQL example as inspiration for a **synthetic acceptance scenario**, not as a claim that
Cicada can already execute learned procedures. A first session establishes a validated query with
explicit inputs and exclusion rules; it records the artifact and when it applies. A later fresh session
finds the same artifact, explains its basis, and can reuse it without rediscovering the joins. A changed
schema or failed validation invalidates reuse and raises the governed correction path.

G55 tasks: link a versioned artifact to its skill, declare inputs/outputs and verification basis, surface
it in recall, and preserve R2's failure ledger, human gate and bounded rewrites before any execution.
Storing a query is not authority to run it against a live database.

G112 tasks: first ground and update extracted skills; the current Stage-4 writer creates only absent
pages, with empty `source_episodes` and `related` (`api/services/inbox_generator.py:363`). Then compile
standalone bundles with portable artifact links, provenance and deliberate redaction. The AMR exporter
may link selected bundles; it must not turn memory text into executable instructions automatically.

## 4. Ownership-aware composition — G16, parked

Preserve the separate-repos idea for future meetings/shared sessions: read selected banks together,
retain bank-qualified identities, and route writes to an explicit destination associated with the
speaker and permission. Ask when destination is ambiguous. A meeting speaker label is an attribution
input, not sufficient authorization or proof of identity. Never merge people solely because names match.

This is design input to G16/D4, not near-term implementation. Multiple-bank reading and multiple writers
of one bank are separate problems. Keep the D4 research-only ruling (`memory-evolution.md:838`).

## 5. Push-only private-remote backup — G132 / G181

Document a narrower option than device sync: the person configures a private remote they own, and the
primary writer pushes committed snapshots. No pull, merge, rebase, force-push or second bank writer.
Run bank git mutations through the existing writer lock; back up a chosen committed revision, not
uncommitted capture. A non-fast-forward rejection stops and reports divergence without reconciling it.
Remote failure must not prevent local capture; expose which commit last reached the backup and why a
later attempt failed. Restore/import is a separate, deliberate workflow.

**DECIDE/RESEARCH:** privacy of the destination must be explicit. A private hosted git repo does not
provide end-to-end encryption; it can contain complete git history, including formerly deleted content.
This proposal does not supersede G92/G132's encryption/transport decisions or authorize a push. Define
whether the allowed destination is owner-controlled storage, a knowingly accepted plaintext private
host, or an encrypted archive before implementation. Push-only protects writer topology; it is not
sufficient to settle disclosure. Fold this into G132/G181 rather than opening another sync track.

## 6. Demonstrate and measure the benefit — G76 / G148

G76: one short fresh-session continuity demo: save a synthetic preference, start another session, recover
it, show its evidence. Explain which capture/recall automation was installed; do not imply that installing
a skill alone enables hooks. Run a separate AMR export trial with no Cicada runtime on the receiving side.

G148: compare no memory, full context, a faithful AMR skill/filesystem baseline, and Cicada using the same
answer model. Do not label substring search over per-session summaries as the AMR agent baseline. Separate
the released invoked-skill mode from a hypothetical automatically loaded or Dreaming-augmented mode.
Measure corrections, temporal changes, provenance, irrelevant-memory avoidance, actual task success,
latency and token overhead. Use isolated synthetic/benchmark banks; do not spend a plan or read the
owner's bank under the guise of a documentation task. Existing benchmark isolation/clock/engine blockers
in G148 still apply. Richer retrieval is a capability difference until this pass proves an outcome difference.

## Corrections to the supplied comparison and work deliberately excluded

- AMR deletion removes an entry from the current view, **not necessarily from git history**. Its actual
  gap is missing structured validity/archival semantics, not absence of history.
- AMR is not restricted to transcripts: it allows arbitrary files and agent-acquired knowledge. The
  missing part in this release is a comparable ingestion runtime.
- A clean git merge is not semantic agreement. Cicada has explicit claim reconciliation, but locking
  alone does not guarantee every contradiction is detected; current lock coverage has disclosed gaps.
- No installed-client compatibility, migration cost, or accuracy advantage was measured. Export is
  plausible and bounded; reverse import and procedural execution require more design.
- Keep human conflict decisions, S3's report-only checks, deterministic capture, temporal history and
  verifiable provenance. Do not copy agent-authoritative contradiction resolution or unrestricted edits.
- Swarm findings/questions/rejected explanations and a shared reproducible benchmark are useful workflow
  patterns, not a new subsystem to build. Revisit a dedicated surface only if an actual workflow needs it.

## Pickup order

G180 CLI and MCP audit remain the owner's first priority. Develop G186's export after the CLI door is
available; its format can be designed earlier. G55/G112 carry the procedural artifact work, G76 the
continuity demo, and G148 the controlled comparison. Backup remains under G132/G181's decisions;
shared-bank composition stays parked in G16. None of these entries marks functionality as shipped.
