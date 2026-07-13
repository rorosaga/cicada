# SkillOpt (Microsoft) and self-improving skills

- Paper: *SkillOpt: Executive Strategy for Self-Evolving Agent Skills* — Microsoft Research, May 2026.
  <https://www.microsoft.com/en-us/research/publication/skillopt-executive-strategy-for-self-evolving-agent-skills/>
- Code: <https://github.com/microsoft/SkillOpt> (MIT-licensed per coverage; **verify license file directly**)
- Authors (15, MSR): Yifan Yang, Qi Dai, Bei Liu, Kai Qiu, Yuqing Yang, Dongdong Chen, Chong Luo, et al.

> Research note for Cicada's improvement wave. Companion analyses:
> [`honcho.md`](../honcho.md), [`gbrain.md`](../gbrain.md). This doc informs the
> still-open **skill-entity / self-improvement** question — it is not a build commitment.

---

## TL;DR

- **"SkillOpt" is real and exactly on-topic.** It is a Microsoft Research framework (paper + open-source repo, May–June 2026) that treats an agent's **`skill.md` document as a trainable parameter** and optimizes it in *text space* for a **frozen** LLM — no weight updates. This is uncannily close to Cicada's markdown-skill-entity idea, including a **"SkillOpt-Sleep" nightly-evolution extension** that mirrors Cicada's Sleep cycle by name. **(Verified via paper page, GitHub, multiple independent write-ups.)**
- **The core mechanism is a validation-gated edit loop:** `rollout → reflect → aggregate → select → update → evaluate`. A *separate optimizer model* turns scored trajectories (including failures) into **bounded add/delete/replace edits** on one markdown file, and **an edit is committed only if it strictly improves a held-out validation score.** This monotonic gate is the whole trick. **(Verified.)**
- **The failure mode this guards against is documented and severe.** Independent work on **"library drift"** shows that ungoverned self-evolving skill libraries can drop **below the no-skill baseline**: LLM-authored skills delivered **+0.0pp** vs human-curated **+16.2pp**; self-generated skills can average **−1.3pp**. Self-improvement without a validation gate and lifecycle management actively hurts. **(Verified — this is the most important cautionary finding for Cicada.)**
- **For Cicada:** the high-leverage borrow is **not** "let the agent rewrite its skills freely." It's the *discipline*: record failures-with-reasons on skill entities, propose bounded edits during Sleep, and **gate every rewrite behind a measurable improvement check + git-revertible provenance.** Cicada's git/markdown substrate is a near-perfect host for this; what it lacks is the **scored-rollout validation harness** that makes the gate meaningful.
- **Honest caveat:** SkillOpt assumes **benchmarks with automatic scoring** (math, code, agentic tasks). Cicada is a *personal* memory system with **no automatic ground-truth reward**. Porting the full optimizer is not viable; porting the *governance pattern* (failure-memory + bounded edits + a weaker, human-or-heuristic gate) is.

---

## Findings

### 1. What SkillOpt actually is (verified)

SkillOpt bills itself as "the first systematic, controllable **text-space optimizer for agent skills**." Instead of fine-tuning weights or doing loose self-revision, it borrows **weight-optimization discipline** and applies it to a single natural-language skill document that conditions a **frozen** target model.

- **Skill representation:** a compact `best_skill.md` artifact, typically **300–2,000 tokens**, deployed as frozen instructions with **zero inference-time optimizer calls at deployment** (the optimizer runs only during "training"). The skill doc *is* the learnable parameter space.
- **Training loop:** `rollout → reflect → aggregate → select → update → evaluate`.
  1. Run the agent on training tasks, producing scored trajectories (rollouts).
  2. *Reflect* on what went right/wrong (this is where failure signal enters).
  3. *Aggregate* reflections across rollouts.
  4. A **separate optimizer model** proposes **bounded add/delete/replace edits** to the skill doc, sized by a **"textual learning-rate budget."**
  5. **Validation gate:** "an edit is accepted only when it **strictly improves a held-out validation score**." Rejections go to a **rejected-edit buffer**; **epoch-wise slow/meta-updates** stabilize training (direct analogues of momentum / learning-rate schedules).
- **Backends/harnesses:** 7 target models (OpenAI, Azure, Claude, Qwen, MiniMax) across **3 harnesses — direct chat, Codex CLI, Claude Code CLI.**
- **Results:** across **6 benchmarks × 7 models × 3 harnesses = 52 cells**, SkillOpt is **best or tied on all 52**, beating human-written, one-shot-LLM, **Trace2Skill, TextGrad, GEPA, and EvoSkill** skills. On GPT-5.5 it lifts no-skill accuracy by **+23.5 (direct chat), +24.8 (Codex), +19.1 (Claude Code)**.
- **Transferability:** optimized skills retain value **across model scales, across Codex↔Claude Code harnesses, and to a nearby math benchmark** with no re-optimization. The artifact is portable, like Cicada's markdown.
- **SkillOpt-Sleep:** the repo references an extension doing **nightly offline evolution** — replaying past sessions/tasks to consolidate "validated skills behind a held-out gate." This is *literally* a Sleep-cycle for skills. **(Verified the name and gist; exact mechanics not deeply documented in what I could fetch — treat specifics as inferred.)**

Sources: [MSR paper page](https://www.microsoft.com/en-us/research/publication/skillopt-executive-strategy-for-self-evolving-agent-skills/) ·
[GitHub](https://github.com/microsoft/SkillOpt) ·
[VentureBeat](https://venturebeat.com/orchestration/microsofts-open-source-skillopt-automatically-upgrades-ai-agent-skills-without-touching-model-weights) (403 on fetch, but indexed title/abstract corroborate licensing + workflow) ·
[explainx.ai](https://explainx.ai/blog/microsoft-skillopt-self-evolving-agent-skills-optimization-2026) ·
[Flowtivity](https://flowtivity.ai/blog/microsoft-skillopt-train-ai-agent-skills/).

### 2. The lineage SkillOpt sits in (verified)

SkillOpt is the latest, most disciplined point on a well-established line:

- **Voyager** (2023) — pioneered the **frozen-LLM skill library**: generate executable code per task, store successful programs indexed by NL description, retrieve & compose. No weights touched. ([survey context](https://arxiv.org/pdf/2512.16301))
- **Reflexion** — learn from failure via **verbal self-reflection** stored in an episodic buffer across trials. This is the conceptual ancestor of "record what failed and why."
- **AutoManual** (2024) — agents build **instruction manuals** from interactive environment experience. ([arxiv](https://arxiv.org/pdf/2405.16247))
- **MUSE / EvoSkill / Trace2Skill / GEPA / TextGrad** — the contemporary cohort of self-evolving-skill and text-gradient optimizers SkillOpt benchmarks against and beats.

### 3. The critical cautionary finding — "library drift" (verified, high importance)

*Library Drift: Diagnosing and Fixing a Silent Failure Mode in Self-Evolving LLM Skill Libraries* ([arxiv 2605.19576](https://arxiv.org/html/2605.19576)) is the most important paper here **for Cicada's safety**:

- **The failure:** skill libraries accumulate artifacts **without lifecycle management**, and performance **degrades below the no-skill baseline**. Three stages: unbounded accumulation without quality signal → retrieval degradation as the library grows → **stale skill injections that actively mislead.**
- **The damning numbers:** "LLM-authored skills deliver **+0.0pp** gain while human-curated ones deliver **+16.2pp**." A separate benchmark (SkillsBench) found self-generated skills averaging **−1.3pp** vs skill-free.
- **The fix ("Ratchet Recipe"):**
  1. **Outcome-driven retirement** — retire a skill once enough trials accumulate (paper: 100+) and its empirical contribution drops below a threshold (−0.10).
  2. **Bounded active-cap** — a hard limit (paper: 50 skills) to stop retrieval rot.
  3. **Meta-skill authoring prior** — constrain LLM-written skills to a consistent style; this alone was **57% of the total gain**, i.e. *how* skills are written matters more than *that* they're written.
- **Negative result worth citing:** *over-aggressive* retirement pushed performance **−0.019 below the no-skill floor** — governance itself can harm if mistuned.

**Takeaway:** self-improving skills are net-negative by default. The value is entirely in the **governance layer** (validation gate + retirement + write-style prior). SkillOpt's strict-improvement gate and Library-Drift's retirement/cap are two halves of the same lesson.

### 4. Honest confidence assessment

| Claim | Confidence |
|---|---|
| SkillOpt exists, is Microsoft Research, optimizes a `skill.md` for a frozen model | **High** (paper + repo + 4 write-ups) |
| The `rollout→…→evaluate` loop + strict-improvement validation gate | **High** (consistent across paper page + repo) |
| Specific numbers (+23.5/+24.8/+19.1; 52 cells; 300–2,000 tokens) | **Medium-High** (from secondary fetches of primary pages; verify against the PDF before citing in thesis) |
| MIT license | **Medium** (reported; check `LICENSE` in repo directly) |
| SkillOpt-Sleep internal mechanics | **Low-Medium** (name confirmed, details inferred) |
| Library-drift numbers (+0.0 / +16.2 / −1.3 / caps) | **Medium-High** (from the arxiv HTML; verify the exact figures) |

---

## What this means for Cicada

Cicada already has **skill-type entities** (procedural memory: preferences, routines, workflows) and **entity-body rewrites** during Sleep. SkillOpt + library-drift tell us how to make those *self-improving without being self-harming*. Concretely:

1. **Add a "failure ledger" to skill entities.** Cicada's edge against everyone here is **transparency**. When a skill entity's guidance leads to a bad outcome (user corrects the agent, rejects a nudge, contradicts a stored preference), record a structured **failure note**: `{episode, what the skill recommended, what actually happened/was corrected, inferred reason}`. Store it on the skill page (a `## Failures` section) or in frontmatter. This is Reflexion's episodic buffer, made **git-versioned and human-readable** — strictly better than an opaque buffer for a thesis about *observable* memory.

2. **Make Sleep the optimizer, with bounded edits.** Map SkillOpt's loop onto Sleep stage 4 (Pattern Detection & Skill Extraction):
   - *reflect/aggregate* = scan accumulated failure notes for a skill entity.
   - *update* = propose a **bounded add/delete/replace edit** to the skill body (not a free rewrite — bound it, like SkillOpt's learning-rate budget, to avoid thrash).
   - Commit as a normal Sleep git commit with a new trigger type, e.g. **`sleep/skill_revision`**, so `git blame` shows exactly which failures drove which line. This *is* SkillOpt's provenance, for free, in Cicada's existing substrate.

3. **The hard part — the validation gate.** SkillOpt's gate needs an automatic score; Cicada has **no ground-truth reward** for personal memory. Options, weakest-honest-first:
   - **Human-in-the-loop gate (recommended default):** a skill rewrite becomes a **nudge** ("I've been getting X wrong; propose changing the skill from A→B — approve?"). The user *is* the validation gate. Fits Cicada's "agent proposes, user disposes" principle perfectly and needs no new infra.
   - **Heuristic regression gate:** before committing a rewrite, replay the **stored failure episodes** against old vs new skill text with an LLM judge; accept only if the new text would have avoided more failures than it introduces. This is a poor-man's held-out validation — cheap, runs in Sleep, no labels needed. Mark clearly in the thesis as an *approximation* of SkillOpt's gate, not the real thing.
   - **Decay-as-gate:** if a skill's failure notes pile up and no rewrite is approved, **drop its confidence** (reuse temporal decay) so the agent trusts it less. Absence-of-correction becomes implicit validation. This reuses Cicada's signature mechanism.

4. **Adopt the library-drift governance, cheaply.** Cicada *already* has most of it and should say so in the thesis:
   - **Retirement** = existing status lifecycle (`active→decaying→archived→dropped`) + confidence threshold. Add an **outcome-driven** trigger: a skill whose failure notes outweigh its confirmations gets a decay nudge.
   - **Active-cap** = a soft cap on skill-type entities surfaced to the agent per query (Bookworm already does relevance filtering; just bound the skill slice).
   - **Meta-skill authoring prior** = the single cheapest, highest-value borrow: a **fixed house style / template for how skill entities are written** (imperative, scoped, falsifiable). Library-drift says this was 57% of the gain. Cicada's YAML+markdown schema is already a partial prior; tighten the *body* prose convention.

5. **Generalize to all entity-body rewrites, not just skills.** Cicada rewrites entity bodies during conflict resolution too. The same pattern — *record why the old text was wrong → propose a bounded edit → gate it → git-blame the provenance* — applies to any entity. SkillOpt is narrowly about skills; Cicada can frame this as a **unified "validation-gated, failure-driven entity revision"** mechanism, which is a cleaner thesis contribution than copying SkillOpt 1:1.

**Where Cicada stays differentiated:** SkillOpt optimizes against *benchmarks* for *task accuracy*; Cicada optimizes a *personal knowledge graph* with the *user as ground truth*, **end-to-end git-transparent**, with **decay** as a built-in retirement signal and a **human curation app** as the gate. That combination is novel — no one in this lineage has the human-facing, git-blamed, decay-governed version.

---

## Recommendation

**Adopt the SkillOpt + Library-Drift *governance pattern*, not the SkillOpt optimizer.** Specifically, for the thesis, implement a **failure-driven, validation-gated skill (and entity-body) revision** loop inside Sleep:

1. **Failure ledger** on skill/entity pages (a `## Failures` section, structured, git-versioned) populated when the user corrects or contradicts the agent. **(Low effort, high thesis value — pure transparency win.)**
2. **Bounded, provenance-tagged rewrites** in Sleep stage 4 under a new `sleep/skill_revision` trigger, so every rewrite is `git blame`-traceable to the failures that caused it.
3. **Human-in-the-loop validation gate by default** (rewrite → nudge → user approves), with an **optional LLM-judge replay** over stored failure episodes as a lightweight automatic gate. Be explicit in the thesis that this is an *honest approximation* of SkillOpt's held-out validation, since personal memory has no automatic reward.
4. **Reuse existing decay + status lifecycle for retirement/active-cap**, and **tighten the skill-body writing convention** (the meta-skill prior — cheapest 57% of the gain).

Frame in the thesis as: *SkillOpt validates the direction (markdown skills as trainable artifacts, nightly evolution behind a gate) from an independent, benchmarked, Microsoft team — and Library-Drift proves the danger of skipping the gate; Cicada's contribution is the **human-facing, git-transparent, decay-governed** instantiation of that loop where the user, not a benchmark, is the validator.* This is the same "architectural validation + distinct contribution" framing already used for gbrain.

**Do not** build a full scored-rollout optimizer — it presumes ground-truth labels Cicada doesn't have and is out of scope/risk for a capstone.

---

## Open questions (need Rodrigo's input)

1. **Scope for the thesis:** ship the full failure-ledger → bounded-rewrite → gated-revision loop, or *only* the failure-ledger + propose-as-nudge (and leave the LLM-judge gate as future work)? The latter is far less risky for a capstone and still demonstrably novel.
2. **Gate choice:** human-only gate (cleaner, fits UX principles, zero eval infra) vs. add the LLM-judge replay gate (more "SkillOpt-like", but adds evaluation complexity and cost). Which do you want to defend?
3. **Where do failure notes live** — a `## Failures` markdown section (human-readable, git-friendly, my default) or structured frontmatter (programmatic, but bloats YAML and fights the "git handles history, not frontmatter" rule)? Section is more consistent with the existing "no changelog in frontmatter" decision.
4. **Does this expand the closed entity-type set or stay within `skill`?** Recommend staying within `skill` + generalizing to any entity body — but confirm you don't want a new `failure`/`lesson` type (I'd argue against it; it pollutes the graph).
5. **Benchmark angle:** SkillOpt and library-drift both report against public benchmarks. Pairs with the gbrain "run a public benchmark (LongMemEval)" open item — is a *self-improvement* benchmark (does the agent get fewer corrections over time on repeated tasks?) worth a small Results-section experiment, or out of scope?
6. **Verify before citing:** pull the actual PDF + repo `LICENSE` to confirm the headline numbers, token sizes, license, and SkillOpt-Sleep mechanics — I marked these Medium confidence and they came via secondary fetches.
