# Procedural / preference memory & skill libraries

Research sweep on the best ways to capture and retrieve "how the user likes things done" and
reusable procedures: Voyager-style skill libraries, reflection-derived rules/preferences,
instruction memory, and when/how to surface them proactively.

---

## TL;DR

- **Procedural memory is underserved** relative to episodic and semantic memory in current
  frameworks. Most production systems (Mem0, LangMem, Letta) acknowledge it but admit tooling
  is still early-stage. The gap is real and worth owning.
- **Two distinct sub-types exist** and need different storage strategies: (a) *skills* —
  reusable step-by-step procedures that can be directly executed or composed (Voyager model),
  and (b) *preferences/style rules* — soft behavioral constraints ("Rodrigo always wants the
  FastAPI router split by domain", "prefers terse bullet summaries") that modify how a task is
  done, not what task is done.
- **Best storage pattern for skills:** natural-language header + structured body (steps,
  preconditions, postconditions, verified-in context), embedded as a vector chunk, surfaced
  by semantic similarity at task-start. Voyager proved that executable skill libraries produce
  3.3× more unique outputs and 15.3× faster progression than agents that regenerate from scratch.
- **Best storage pattern for preferences:** short declarative statements tagged with scope and
  confidence, stored in a dedicated section of a flat file (or a `preferences/` folder), injected
  as a block into the system prompt at conversation start — NOT retrieved on demand, always in
  context if compact enough.
- **Proactive surfacing matters more than retrieval accuracy.** The hard problem is not storage;
  it is injecting the right preference/skill at the right moment without bloating the context
  window. Trigger strategies: semantic similarity at task recognition, scope tags (domain,
  entity, tool), and recency/frequency weighting.
- **Conflict and change detection is unsolved.** When a preference changes ("actually I want
  tests before implementation now"), the old rule must be invalidated or versioned, not silently
  accumulated. Git versioning on markdown files solves the audit trail; the Sleep cycle must
  add contradiction detection logic.

---

## Findings

### 1. Voyager's skill library (the canonical reference)

Voyager ([Wang et al., 2023](https://arxiv.org/abs/2305.16291)) is the most cited example of
procedural memory done right for LLM agents. Key mechanics:

- Every verified Minecraft routine is stored as **runnable JavaScript** (executable, not just
  descriptive).
- Each skill is **indexed by a natural-language description** (not by a code signature), enabling
  retrieval via semantic similarity.
- Skills are **compositional**: when a novel task arrives, the agent retrieves 2–5 relevant
  skills and combines them rather than generating from scratch.
- Skills are **verified before storage**: an iterative prompting loop incorporating environment
  feedback and self-verification must pass before a skill enters the library.
- Result: agents with the skill library solve new tasks far faster and accumulate far more
  diverse behaviors than baseline agents that regenerate every time.

The insight for Cicada: even if Rodrigo's "skills" are not executable code but are *behavioral
templates* ("when asked to scaffold a FastAPI service, use this folder structure..."), the same
architecture applies — store verified examples, retrieve by semantic similarity, compose.

### 2. LangMem's three-tier model with procedural as system-prompt rewriting

LangChain's LangMem SDK ([launch post](https://www.langchain.com/blog/langmem-sdk-launch))
formalizes three memory types with distinct storage targets:

| Type | Storage target | Format |
|------|---------------|--------|
| Episodic | Collection (vector store) | Conversation chunks |
| Semantic | Profile or Collection | Structured facts / entity profiles |
| **Procedural** | **Prompt rules or Collection** | **Updated system instructions** |

Procedural memory in LangMem works by **rewriting the agent's own system prompt** — the agent
observes failures or feedback, extracts a lesson ("I should always ask for the return type
before writing a function"), and appends or modifies a rule in its core prompt. Three
optimization algorithms are supported: metaprompt, gradient-style (critique then propose), and
single-step prompt_memory.

Risk: unconstrained self-rewriting leads to drift and bloat. LangMem itself flags that
consistency verification and temporal decay are required to prevent agents from reinforcing
suboptimal patterns.

### 3. Memp: distilling trajectories into two levels of abstraction

[Memp (Fei et al., 2025)](https://arxiv.org/abs/2508.06433) distills past agent trajectories
into two levels:

- **Fine-grained**: step-by-step instructions (how exactly to execute a known task type)
- **Script-like abstractions**: higher-level templates reusable across more diverse tasks

Build, Retrieval, and Update are treated as separately tunable dimensions. Key finding: an
agent that carries procedural memory built by a *stronger* model can transfer performance gains
to a *weaker* model — procedural memory is a form of model compression / knowledge
distillation. Evaluated on TravelPlanner and ALFWorld, procedural memory consistently improves
success rate and efficiency.

### 4. Preference-Aware Memory Updates (sliding window + change detection)

[Preference-Aware Memory Update (2025)](https://arxiv.org/pdf/2510.09720) addresses the
instability of naive preference accumulation:

- Uses **sliding window + exponential moving average** over preference signals to detect when
  a preference has genuinely shifted (vs. a one-off exception).
- Change detection triggers a **targeted update** rather than appending a contradictory new
  preference.
- Data model: preferences are tagged as preference-type (distinct from facts), versioned with
  timestamps, and carry frequency/strength metadata.

This is directly relevant to Cicada's Sleep cycle: the consolidation batch should treat
preference signals like belief updates — not append-only, but with explicit invalidation.

### 5. Hindsight's opinion network — separating facts from preferences

[Hindsight (2024)](https://arxiv.org/html/2512.12818v1) explicitly separates an **opinion
network** (subjective, preference-type memories with confidence scores and associated entities)
from world/experience networks (objective facts). Each opinion is a self-contained unit: text,
confidence, timestamp, and entity links.

The architecture also introduces a "disposition space" — parameterized reasoning styles
(skepticism, literalism, empathy) that shape how the agent reasons over identical facts in
different contexts. While Cicada doesn't need the disposition dimensions, the separation of
"fact" vs. "opinion/preference" as first-class distinct memory types is sound and well-reasoned.

### 6. Honcho's user representation model (belief state over the user)

[Honcho (Plastic Labs, 2025)](https://dev.to/andrew-ooo/honcho-review-plastic-labs-agent-memory-layer-2026-2kb4)
treats memory not as retrieval but as **reasoning about who the user is**. Every turn assembles:

- **Base context**: session summary, user representation (stable model of preferences/identity),
  user "peer card" (communication style), AI self-representation.
- **Dialectic supplement**: LLM-synthesized reasoning about the user's *current state* — what
  matters right now in this conversation.

This (observer, observed) framing is what Rodrigo identified as appealing. The key insight: a
user's preferences are not a list of facts; they form a *model* that must be reasoned over.
Honcho achieves 90.4% on LongMem S using only median 5% of available context — because it
injects a compressed, reasoned user model, not raw episodic chunks.

### 7. Proactive surfacing: trigger conditions and injection strategy

From [memory architecture for proactive agents (Moses, 2026)](https://medium.com/data-science-collective/the-memory-problem-changes-when-agents-stop-waiting-to-be-prompted-5a2939200fcf):

- Preferences should **point into** a known entity/context graph rather than duplicate facts.
  A preference node says "for tool X, Rodrigo prefers Y" — the entity graph supplies X's
  current state.
- Trigger conditions for injection: (a) semantic similarity of task description to a stored
  preference/skill, (b) entity recognition (the current task involves entity X that has
  attached preferences), (c) tool recognition (agent is about to use tool T that has stored
  usage patterns).
- **Bounded injection**: do not inject all matching preferences; rank by recency + frequency +
  cosine similarity, inject top-k. The research consistently shows model performance degrades
  with too many injected memories.

### 8. The production gap

Per [Mem0's State of AI Agent Memory 2026](https://mem0.ai/blog/state-of-ai-agent-memory-2026):
procedural memory "is an area where the tooling for managing procedural memory specifically is
still early-stage." Even the best production frameworks treat it as a secondary concern. This
is a genuine research/engineering gap, not just a thesis contribution.

---

## Concrete data-model ideas for Cicada

### A. Two new first-class entity-like types: `skill` and `preference`

Both live as markdown files under dedicated directories, not mixed with `entities/`. This
separates semantic facts (who Rodrigo is, what projects exist) from procedural/preference
knowledge (how Rodrigo likes things done).

**`memory/skills/` — reusable procedures**

```yaml
---
type: skill
id: skill_fastapi_scaffold
title: "FastAPI service scaffold"
scope: [tool:FastAPI, domain:backend]
status: active
confidence: 0.92
verified_in:
  - ep_2026-03-15_002
  - ep_2026-04-01_007
created: 2026-03-15
last_used: 2026-04-01
version: 2
---

## Trigger conditions
When asked to create a new FastAPI service or API module.

## Procedure
1. Create `api/routers/<domain>.py` with an `APIRouter` instance.
2. Register it in `api/main.py` under the matching prefix.
3. Each endpoint takes a Pydantic request/response model from `api/models/`.
4. Tests go in `tests/test_<domain>.py` using pytest + httpx.AsyncClient.

## Preconditions
- Python 3.11+, FastAPI installed.
- Existing `api/main.py` with `include_router` pattern.

## Postconditions / definition of done
- New router returns 200 on at least one test case.

## Notes
Rodrigo prefers terse docstrings; no autogenerated preamble.
```

**`memory/preferences/` — style/behavioral rules**

```yaml
---
type: preference
id: pref_summary_style
scope: [task:summarize, task:explain]
strength: 0.88         # 0–1, derived from frequency + explicit confirmation
confidence: 0.88
contradicts: []        # ids of invalidated older preferences
created: 2026-01-20
last_updated: 2026-05-10
source_episodes:
  - ep_2026-01-20_003
  - ep_2026-05-10_001
version: 3
---

Rodrigo prefers terse bullet-point summaries over prose paragraphs. Maximum 6 bullets.
Include a TL;DR sentence at the top. No filler phrases ("It's worth noting that...").
```

### B. Sleep cycle extraction for procedural memory

During Sleep stage 4 (Pattern Detection), add a dedicated pass:

1. Scan episodes for **repeated task patterns**: "Rodrigo asked to scaffold FastAPI three times
   this month; extract the common procedure."
2. Scan for **explicit corrections**: "No, I always want X" or "Stop doing Y, I prefer Z" →
   these are direct preference signals, highest confidence.
3. Scan for **implicit style signals**: repeated manual edits to agent output in a particular
   direction → infer the underlying preference.
4. On preference change detection: set `contradicts: [old_pref_id]` in the new preference;
   update old preference's `status: superseded`.

### C. Retrieval and injection at conversation start

The `/ask` endpoint and any MCP Bookworm trigger should:

1. **Always inject** the top-N preferences (sorted by `strength * recency`) whose `scope`
   intersects the detected task domain. Preferences are short; this should cost <200 tokens.
2. **Retrieve skills** by semantic similarity to the task description (sqlite-vec query against
   skills); inject the top 1–2 most relevant if similarity > threshold (e.g., 0.75).
3. **Do not mix** skills and preferences into the entity graph traversal path — separate
   retrieval paths, separate context sections in the injected prompt block.

### D. Skill verification before storage

Borrow from Voyager: a skill should only enter `memory/skills/` after its procedure has been
verified (either explicitly confirmed by Rodrigo, or used successfully in ≥2 separate episodes
without correction). The Sleep cycle tracks `pending_skills/` until this threshold is met.

### E. Git + versioning as conflict log

Because skills and preferences live as markdown files:

- `git blame memory/preferences/pref_summary_style.md` shows exactly when each rule was
  written and by which Sleep cycle or agent.
- Version counter in frontmatter enables the `/entities/{id}/history` endpoint (or an
  analogous `/skills/{id}/history` and `/preferences/{id}/history`) to render the changelog
  of a behavioral rule — including when it was invalidated and why.

---

## Tradeoffs / where it fails

**Preference drift without change detection.** If Sleep simply appends new preferences without
invalidating conflicting ones, the injected preference block becomes contradictory. The agent
gets confused ("summarize in bullets" vs. "always include a prose introduction"). This is the
main failure mode. Mitigation: the `contradicts:` field and a contradiction-detection pass in
Sleep.

**Skill staleness.** A skill verified in March may become wrong by June (Rodrigo switched
libraries, changed the project structure). Decay rate should apply to skills too, not just
semantic entities. If a skill has not been referenced in N cycles, flag it for review.

**Preference vs. fact confusion.** "Rodrigo uses FastAPI" is a fact (entity). "Rodrigo prefers
to structure FastAPI routers by domain" is a preference. The Sleep LLM may misclassify. Need
explicit prompt engineering in the extraction stage to force this distinction.

**Context window cost.** Always injecting preferences adds fixed token overhead per conversation.
If preferences accumulate to 50+ items, injection cost becomes non-trivial. Mitigation: scope
tags allow filtering to only domain-relevant preferences; strong decay/archive threshold prunes
old ones.

**Unverified skill hallucination.** If Sleep promotes a "skill" from a single episode where
the agent confidently described a procedure that turned out to be wrong, that skill will be
injected and cause errors in future tasks. The ≥2-episode verification threshold is essential.

**Cold-start / bootstrapping.** On day one, there are no skills or preferences. The agent
behaves generically. Procedural memory requires sustained use to become valuable. This is
expected but worth setting expectations around — the value accrues over months, not days.

---

## Open questions

1. **Where does the line between a `preference` and a `skill` fall exactly?** A preference
   modifies behavior; a skill defines behavior for a task type. But "when writing commit
   messages, always include the ticket number" is both. A single `procedure` type with a
   `style: [preference | skill | hybrid]` field may be cleaner.

2. **Should skills be executable (code/templates) or descriptive (prose steps)?** For Cicada's
   use case (a personal assistant, not a Minecraft bot), prose steps are probably sufficient
   and far easier to maintain. But for coding tasks, storing a scaffold template or a code
   snippet alongside the prose may be more useful to the agent.

3. **How should multi-context preferences be handled?** Rodrigo noted he holds different
   beliefs depending on context (engineer-self vs. family-self). Scope tags help, but they
   assume the agent can detect which context it's in. A `context_trigger` field (e.g.,
   "activate when topic is work/tech") may be needed.

4. **Honcho's dialectic supplement (dynamic reasoning about user state) vs. static preference
   injection:** Would a lightweight LLM pass at conversation start that *reasons* over all
   stored preferences to produce a custom summary ("right now, Rodrigo is in thesis-writing
   mode; surface these three rules") outperform raw injection? Possibly yes, at higher compute
   cost. Worth experimenting.

5. **Should preference confidence use the same 0–1 decay model as entity confidence?** Intuition
   says yes — a preference not exercised in 60 days should fade — but the right decay rate for
   preferences is probably much slower than for episodic entities. Separate `decay_rate`
   defaults for preference vs. entity types.

6. **Multi-agent attribution for skill evolution.** If the Sleep cycle (model A) extracts a
   skill and a later conversation (model B) refines it, who "owns" the current version? The
   `Cicada-Author` trailer on the git commit handles attribution, but the skill page itself
   could carry a `refined_by` field for human-readable clarity.
