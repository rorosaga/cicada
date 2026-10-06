# G73 — Start prompts: reusable objective briefs

**Owner idea, 2026-10-06; working product name “start prompts.” Not implemented.** Save prompts that served particular objectives, and reuse them with other models, agents or projects. Keep promising candidates as well as prompts with actual successful-use evidence. This extends the existing prompt-library row, not a second backlog idea.

[G73](../goals/memory-evolution.md#g73) owns the user-facing save/find/adapt/reuse workflow; [G112](../goals/memory-evolution.md#g112) can later package validated prompts into portable skills. [G110](../goals/memory-evolution.md#g110) supplies current project context when starting or continuing work. G48/G118 supply source/session provenance, G113 feedback and G127 the mascot-creation prompt use case. Priority: **P2**, alongside portable skills. The simple library does not wait for skill compilation, executable procedures or a model-funded consolidation.

## User-provided candidate

The owner supplied this excerpt, attributed to the Anthropic team. No original source URL or full prompt was supplied; retain that attribution as supplied, the omission marker and candidate status. It has not been evaluated here.

> Your job is to facilitate all things related to the performance of the claude.ai website and desktop app. Your responsibilities include monitoring deploys for performance regressions, assessing the accuracy and comprehensiveness of existing telemetry, maintaining well-curated observability dashboards, proactively implementing solutions for observed issues and low-hanging fruit, proposing performance project opportunities, and communicating with your human teammates. […]
>
> The ultimate goal for this channel is for you to become as autonomous as possible, but today we know that isn’t yet possible.

This is a useful candidate for a performance/observability objective: a mission, recurring responsibilities and a desired autonomy level. Candidate usefulness is a hypothesis, not proof that the prompt improves any model. The excerpt's missing section cannot be reconstructed or treated as supplied instructions.

## Core workflow

- **Save intentionally:** select a prompt from a conversation, paste one or import a supplied artifact, and name its objective. Keep exact permitted text and source references, original versus user-edited text, date and optional source session/project/model. Apply the existing secret scrub and disclose text changes rather than claiming an altered copy is verbatim. Capture is file I/O; no LLM is required to save it.
- **Collect candidates:** a person or agent can propose a promising prompt from actual captured use or an external source. Label imported, proposed and used states clearly; automatic extraction proposes, never declares success or overwrites the original. No model call at capture time. Saving an excerpt does not imply the full prompt was captured.
- **Find by objective:** browse/search goals such as performance investigation, project planning, design exploration or research. Recall can suggest a small relevant set with purpose, provenance, use evidence and known limits. Make the objective meaningful, rather than relying only on the prompt's opening words or source model.
- **Adapt visibly:** preserve the original, then create a linked version with explicit inputs such as target project, system, audience, tools, deliverables and autonomy/approval boundaries. Replace project-specific details with parameters deliberately; do not silently discard a useful constraint. Flag unsupported capabilities or unfilled inputs before presenting a ready-to-use prompt.
- **Reuse:** preview/copy the chosen prompt or hand it to a supported agent at the person's request. Show which version and project inputs were used. Output is ordinary Markdown/plain text, readable without Cicada; harness-specific wrappers or optional skills are separately labeled. Stored prompt text remains data until selected for the task; it does not grant tools, credentials or permission to contact people.
- **Learn from use:** link a use to the actual session, model/harness, adaptation and observed outcome. A user's “this worked” is a user verdict; an agent's suggestion is not a verified result. Keep limitations and failed uses. Reuse counts are not quality proof, and success in one project/model does not establish universal effectiveness.

## Record and presentation requirements

Keep an identity/name, objective, permitted original text, version/variant lineage, source attribution and completeness, required inputs, optional target assumptions and tool requirements. Add dated use/outcome references and candidate/user-endorsed/archived state. Separate source author, the person who saved/edited it and the agent/model that used it. Labels must describe the evidence behind endorsement; archive superseded versions without deleting provenance.

Provide a Prompts/Start prompts surface with objective filters, candidate/reusable status and a detail view for text, inputs, source, variants and uses. Expose the same governed save/read/update/reuse operations over MCP and the G180 CLI when available. A prompt merely existing inside a transcript or an agent setup string does not implement this workflow.

Choose one Markdown/git representation in the implementation plan (typed episode/artifact plus existing entity links where useful). Respect the closed entity taxonomy; do not add a `prompt` entity type implicitly. Derived search is disposable. Keep runtime bank data private and public examples synthetic or explicitly user-supplied public excerpts. Keep a reusable base brief distinct from per-session G110 working context, with links between them; neither duplicates `_state.md` as a second authoritative memory.

## Slices and acceptance

1. **Save and reuse, no compiler:** save the supplied excerpt as a candidate with its objective, source/completeness and exact permitted text. Find it in a fresh session by objective, inspect it, and copy/export it. No Sleep run required.
2. **Variants and project inputs:** adapt a synthetic performance brief from `alpha-project` to `beta-project`, showing changed parameters and maintaining a link to the immutable source version. No project-private details carry across accidentally.
3. **Cross-model use:** run the chosen brief in two supported harnesses/model families with declared capabilities; inspect the generated plan/work rather than scoring merely successful import. Record generic outcomes publicly. Preserve model-specific limits; missing tools cannot be hidden by a provider-neutral template.
4. **Candidate selection and feedback:** an agent proposes a captured prompt, the person can keep/edit/archive it, and subsequent relevant recall distinguishes untested candidates from evidence-backed uses. Corrections never silently rewrite the saved original.
5. **Continuity and later skills:** a selected start prompt links to the work/session it initiated; G110 automatically continues that work later. G112 may compile a validated brief into a standalone skill, while G55 governs any executable artifacts. The plain prompt remains usable independently.

No implementation or model execution was performed while recording this idea.
