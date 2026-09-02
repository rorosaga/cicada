# Subscription-Only Cicada — Research Synthesis & Recommended Architecture

**Date:** 2026-08-21 · **Status:** research complete, synthesis judged · **Repo:** `/Users/rorosaga/Documents/roros_lab/cicada`

*Provenance: produced by a 15-agent Claude Code research workflow (2 repo-grounding readers, 4 web researchers, 5 adversarial claim-verifiers, 3 architecture designers under different lenses, 1 synthesis judge). Only the five claims in the "Verified claims" table were independently double-checked; everything else is researched-with-sources — the "Load-bearing claims NOT verified" list at the bottom is the re-confirmation checklist before building.*

**Goal:** make Cicada fully useful for someone who pays ONLY for a Claude plan (Pro/Max) or a ChatGPT plan (Plus/Pro) — no API keys, no extra cloud spend. Two halves: (a) capture + recall inside the chat sessions the user already has; (b) Sleep-cycle consolidation powered by that same subscription (or fully local), on a schedule or opportunistically.

---

## TL;DR

Build the **Session-Native Engine Ladder**: Design A (Session-Native) as the base — a Claude Code plugin (SessionStart primer hook, Stop/SessionEnd capture, PreCompact flush, both skills, MCP registration, new `cicada_commit` tool) plus a Codex CLI mirror for ChatGPT-plan users — with Design C's engine architecture grafted underneath (implement the reserved `llm_mode="agent"` as a probed ladder: subscription CLI → local Ollama → BYOK → skip-with-queue; make `providers.resolve_llm_fn` the mandatory seam; ship the *proven* driver-style `claude -p` librarian drain first, batch StageJobs later) and Design B's onboarding grafted on top (companion-app plan-picker wizard replacing "paste your key" with vendor OAuth, ungated embedding default killing the hidden HF_TOKEN gate, launchd nightly runner with env-key sanitization and stop-on-rate-limit interruptibility). Two things all three designs independently converged on and are therefore non-negotiable: a **deterministic "structural Sleep"** (decay, hubs, wikilink/claim edges, index rebuild, inbox, git commit — zero LLM, runs nightly no matter what, and finally commits/indexes agentic writes) and **bearer-token auth on localhost:8000 as a launch blocker** (the claude-mem port-37777 audit lesson). The subscription engine is exclusively the official `claude` binary via `claude -p` — never the Agent SDK on OAuth — and all budgeting is done in *invocations with live throttle detection*, never tokens, because the published token figures were refuted. ChatGPT-plan users get the mirror via Codex CLI (`codex exec`, `codex mcp add`, Codex-dialect skill, `~/.codex/sessions` importer); ChatGPT *web* remains export-import by default. Effort ≈ 5–7 focused weeks solo; a Claude-plan user is fully served after ~2.

---

## The problem: API-key onboarding blocks portability

Cicada's consolidation pipeline (litellm, default `gpt-5.4-mini`) assumes an API key, and `install.sh` scaffolds an OpenAI-first `.env` and interactively prompts for `OPENAI_API_KEY`/`ANTHROPIC_API_KEY` — even though the code default for embeddings is already `local` and the whole retrieval stack is already keyless. This is a distribution problem, not a capability problem:

1. **The funnel dies at the key prompt.** Every prior-art tool that asks a consumer for an API key at onboarding (OpenMemory self-host, Letta free tier, Smart Connections chat) stalled at developer-hobbyist scale. The category winner, claude-mem (~91K stars), rides the user's *existing* Claude Code authentication — "no separate API key or account needed."
2. **The user already pays for a frontier model.** A Pro/Max or Plus/Pro subscription is a flat-rate frontier-model budget sitting idle at night. Asking for a second, metered billing relationship to consolidate personal memory is economically and psychologically redundant.
3. **Cicada already proved the alternative.** The 2026-07-14 run consolidated **988 episodes → 442 claims → 74 entities with zero API keys** via the Claude-Code-driven librarian path (`docs/goals/memory-evolution.md`). The architecture works; it just isn't packaged, scheduled, or defaulted.
4. **Privacy composition.** A personal memory system's episodes are the most sensitive data a user has. Free API tiers train on prompts; the subscription path (with training opt-outs) and the local path do not have that shape.

---

## Current key-dependency surface

Exactly **10 production LLM callsites**, all via litellm, every one with a coded no-key degrade. Only 4 route through the intended keyless seam (`api/services/providers.py::resolve_llm_fn`); the rest call litellm directly, which is why `CICADA_LLM_MODE=local` alone does not make the pipeline keyless today.

| # | Callsite | File | Via provider factory? | No-key behavior today |
|---|---|---|---|---|
| 1 | Stage-1 entity/relationship extraction | `api/services/entity_extractor.py` | ❌ direct litellm | Episode requeued (`processed:false`); all-failed → hard abort, queue intact (`sleep_cycle.py:115-123`) |
| 2 | Stage-2 disambiguation judge | `api/services/entity_resolver.py` (~line 690) | ❌ direct | Returns "unsure" → clarification instead of merge; fuzzy >85 path is deterministic and always on |
| 3 | Stage-3 body synthesis | `api/services/conflict_resolver.py` | ✅ | Skip synthesis; entity still updated |
| 4 | Stage-3 contradiction check | `api/services/conflict_resolver.py` | ✅ | `contradiction=None` (no conflict nudge); decay math is deterministic |
| 5 | Stage-4 skill extraction | `api/services/skill_extractor.py` | ✅ | Returns `[]` — zero skills, cycle continues |
| 6 | Stage-5.57 link enrichment | `api/services/link_enrichment.py` (line 252) | ❌ direct | Page marked `enrichment_attempted`; zero-LLM OG-description promotion is the common case; ≤20 calls/cycle cap |
| 7 | `/ask` synthesis (`POST /ask`, MCP `cicada_ask`) | `api/services/ask_service.py` | ❌ direct | Honest 0.15-confidence citation-only answer; empty retrieval short-circuits before any LLM call |
| 8 | Dedup-sweep judge (G21) | `api/services/dedup_sweep.py` | ✅ | Pairs skipped; candidate generation is keyless (local-embedding cosine ≥0.85) |
| 9 | Source-grounded rewrite | `api/services/source_rewrite.py` | ✅ | Dormant — only caller is a benchmark script |
| 10 | Benchmarks (answerer, run_table1, model comparison, retrieval-eval judge) | `benchmarks/` | mixed | Thesis-only; never gates the live product |

**Already fully keyless:** embeddings (local EmbeddingGemma-300M default, keyed modes auto-degrade to local; one-time HF_TOKEN needed to *download* the gated model — see recommendation), the entire retrieval stack, **12 of 13 MCP tools** (only `cicada_ask` touches an LLM, and it degrades), the agentic write path (`agentic_write.write_claim` → deterministic trust-gated Stage-3 reconciler, zero LLM), the Stage-5.56 claim pipeline, all deterministic sleep sub-stages (hubs, wikilink/media/claim edges, inbox generation, git commit), and every capture connector (MCP save, Telegram, media/OG, RSS, bookmarks, notes, all export parsers).

**Known config drift:** `install.sh` scaffolds `CICADA_EMBEDDING_MODE=openai` + key prompts (code default is `local`); `api/.env.example` is LEANN-era; `--skill` installs only the recall skill, never `cicada-librarian`; `llm_mode="agent"` is reserved-but-unimplemented (`api/config.py:~101`); default `ollama_model` is a stale `llama3.1`; `agentic_write.py` has zero git and zero index calls, so librarian writes sit uncommitted and unindexed until a full Sleep runs; nothing anywhere schedules the librarian loop.

---

## What a Claude plan can drive today

| Capability | Plans | Status (2026-08-21) | Source |
|---|---|---|---|
| `claude -p` headless on subscription OAuth (`/login`), no API key | Pro, Max, Team, Enterprise | **VERIFIED confirmed** — OAuth is the documented auth default; `claude setup-token` mints a 1-year subscription token for scripts. Caveats: a stray `ANTHROPIC_API_KEY` silently wins in `-p` mode; `--bare` never reads OAuth and is slated to become the `-p` default | https://code.claude.com/docs/en/authentication · https://code.claude.com/docs/en/headless · https://support.claude.com/en/articles/11145838-use-claude-code-with-your-pro-or-max-plan |
| Headless/SDK billing draws from regular plan pools (separate-credit split **paused** June 15, 2026; still paused) | Pro, Max | **VERIFIED confirmed** | https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan · https://thenewstack.io/anthropic-pauses-claude-agent-sdk-subscription-change/ |
| ToS posture for scripted use | — | **VERIFIED confirmed w/ caveats** — Claude Code is the official scripted-use product, but the Feb 2026 clarification limits subscription OAuth tokens to **Claude Code and claude.ai only** ("including the Agent SDK — is not permitted"); docs recommend `--bare` + API key for general automation | https://code.claude.com/docs/en/legal-and-compliance · https://www.anthropic.com/legal/consumer-terms · https://www.theregister.com/software/2026/02/20/anthropic-clarifies-ban-on-third-party-tool-access-to-claude/5014546 |
| Agent SDK with subscription auth | Pro, Max, Team, Enterprise | **VERIFIED confirmed available per support article — but in tension with the Feb 2026 OAuth clarification above.** This report resolves the tension conservatively: use `claude -p` (the official binary) only | https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan · https://zed.dev/blog/anthropic-subscription-changes |
| Usage limits | Pro, Max | 5-hour rolling session limit + weekly all-models cap are real; **token-denominated figures are UNPUBLISHED — the specific 5M/25M/100M/500M numbers circulating were REFUTED**. Design in invocations, detect throttling live | https://support.claude.com/en/articles/11049741-what-is-the-max-plan · https://techcrunch.com/2025/07/28/anthropic-unveils-new-rate-limits-to-curb-claude-code-power-users/ |
| Hooks (SessionStart/Stop/SessionEnd/PreCompact) for automatic capture | all Claude Code | Believed current, **NOT among the 5 verified claims** — validate payload shapes hands-on | https://support.claude.com/en/articles/9762155-claude-code-hooks |
| Plugin marketplace (`/plugin marketplace add` / `/plugin install`) | all Claude Code | Believed current (claude-mem's shipping vehicle), **not re-verified** | https://github.com/thedotmack/claude-mem |
| Claude Desktop local MCP / `.mcpb` Desktop Extensions | all plans | Believed current (shipped Sept 2025), **not re-verified** | https://support.claude.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop |
| claude.ai web/mobile remote MCP custom connectors | Free (1 connector), Pro, Max+ | Believed current; requires a publicly reachable HTTPS endpoint — **not re-verified**; opt-in only in this design | https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp |
| Cloud Routines (scheduled agents, Anthropic-hosted) | Pro+ | Believed current; **no local filesystem access** — irrelevant to a local-first default path | https://makerkit.dev/blog/tutorials/claude-code-routines-guide |

## What a ChatGPT plan can drive today

All rows researched against official OpenAI docs during this cycle but **none were among the 5 independently verified claims** — re-confirm the load-bearing ones before build.

| Capability | Plans | Status (2026-08-21) | Source |
|---|---|---|---|
| Codex CLI usage included with ChatGPT sign-in | Plus, Pro, Business, Enterprise, Edu (+Free/Go limited-time) | Official; shared 5h + weekly pool, purchasable credits | https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan · https://openai.com/index/introducing-the-codex-app/ |
| `codex exec` headless (`--json`, `--output-schema`, `--sandbox workspace-write`, resume) | same | Official docs; `--output-schema` gives *enforced* structured output — stronger than the Claude path | https://developers.openai.com/codex/noninteractive |
| MCP client (stdio + streamable HTTP), `codex mcp add`, `required=true` halts runs on server failure | same | Official; config in `~/.codex/config.toml`, **shared with the ChatGPT desktop app** | https://developers.openai.com/codex/mcp |
| Skills (`~/.codex/skills/`, SKILL.md, deliberately Claude-shaped) + AGENTS.md | same | Official — the librarian port is a copy + prompt-dialect pass | https://developers.openai.com/codex/skills · https://developers.openai.com/codex/guides/agents-md |
| ChatGPT-account auth for non-interactive runs (auth.json, device-auth, CI/CD guide) | same | Official documented path; one machine per `auth.json`, preserve refreshed tokens | https://developers.openai.com/codex/auth · https://developers.openai.com/codex/auth/ci-cd-auth |
| Codex app **Automations** (local scheduler: RRULE, skills, review queue) | same | Official; machine must be awake; **MCP-tool use inside scheduled runs is implied by shared config but undocumented — validate hands-on** | https://openai.com/index/introducing-the-codex-app/ · https://learn.chatgpt.com/docs/automations |
| ChatGPT desktop app local stdio MCP | unstated (verify on Plus) | Official docs; **which chat surfaces (classic ChatGPT vs Codex/Work threads) invoke local MCP needs hands-on validation** | https://learn.chatgpt.com/docs/extend/mcp |
| ChatGPT web developer-mode custom connectors | Pro: read/fetch confirmed; **Plus unconfirmed**; writes Business/Enterprise/Edu-only | Official article; localhost needs Secure MCP Tunnel (requires a Platform org) or DIY tunnel | https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt · https://developers.openai.com/api/docs/guides/secure-mcp-tunnels |
| ChatGPT Scheduled Tasks / Work cloud tasks | Plus: 5 tasks, hourly max | **Not viable for consolidation** — cloud-only, no local filesystem; agent mode/Operator discontinued | https://help.openai.com/en/articles/10291617-tasks-in-chatgpt · https://help.openai.com/en/articles/11752874-chatgpt-agent |
| Data export (web/mobile backfill) | Free/Go/Plus/Pro | Official; up to 7 days to arrive, 24h link — backfill cadence, not freshness | https://help.openai.com/en/articles/7260999-exporting-your-chatgpt-history-and-data |
| `~/.codex/sessions/**/rollout-*.jsonl` local session logs | same | **Community-documented, unversioned** — defensive parsing required | https://github.com/openai/codex/discussions/3827 |
| Model watch | — | GPT-5.4/5.4-mini leave ChatGPT-auth Codex **2026-08-31** → never pin models in prompts/config | https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan |
| Privacy | Plus/Pro | Conversations may train models unless "Improve the model for everyone" is off — onboarding must say so | https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan |

**ChatGPT bottom line:** Codex CLI is a genuine 1:1 mirror of the Claude Code path (plan-included, headless, MCP, skills, sanctioned non-interactive auth). The only capability gap vs Claude is write-capable MCP in ChatGPT *web* (Business+ only) — the desktop app closes it; export-import covers web/mobile backfill.

---

## Verified claims (trust these over anything else in this report)

Only these five were independently verified. Everything else herein is "researched with sources" or "believed from memory" — flagged where load-bearing.

| Claim | Verdict | Evidence (compressed) | Key sources |
|---|---|---|---|
| June 15, 2026 Agent-SDK/`claude -p` billing split was paused; headless still draws from Pro/Max pools | **CONFIRMED** | Anthropic's live Help Center article still opens with the pause notice (fetched 2026-08-21); "July 10 reinstatement" claims traced to SEO junk and contradicted by the official page | https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan · https://thenewstack.io/anthropic-pauses-claude-agent-sdk-subscription-change/ |
| `claude -p` is the official scripted-use product, exempt from no-automation ToS clauses | **CONFIRMED (with caveats)** | True in substance, but the exemption lives in the Claude Code legal page, not the Consumer ToS; Feb 2026 clarification: subscription OAuth only in **Claude Code and claude.ai** — "including the Agent SDK — is not permitted"; docs recommend `--bare` (API-key) for general scripted calls | https://code.claude.com/docs/en/legal-and-compliance · https://www.theregister.com/software/2026/02/20/anthropic-clarifies-ban-on-third-party-tool-access-to-claude/5014546 |
| `claude -p` works on subscription OAuth, no API key | **CONFIRMED (with caveats)** | Auth-precedence docs confirm; `setup-token` mints 1-year OAuth tokens for CI. Caveats: env `ANTHROPIC_API_KEY` silently wins in `-p` (issue #37686's $1,800 bill); `--bare` never reads OAuth and is slated to become the `-p` default | https://code.claude.com/docs/en/authentication · https://github.com/anthropics/claude-code/issues/37686 |
| Agent SDK authenticates via Pro/Max subscription | **CONFIRMED** | Support article: available on Pro/Max/Team/Enterprise; the pause concerned billing, not auth. **Tension with claim 2's Feb-2026 caveat is unresolved in official sources → this design uses `claude -p` only** | https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan · https://zed.dev/blog/anthropic-subscription-changes |
| Pro ~5M / Max 25M–100M tokens per 5h window, ~500M weekly; a Sleep cycle (~10–50M) fits comfortably | **REFUTED** | Anthropic publishes **no token-denominated limits at any tier**; official weekly expectations were expressed in *hours*; third-party token estimates disagree by ~100×. Any design that sizes batches in tokens is building on invented numbers | https://support.claude.com/en/articles/11049741-what-is-the-max-plan · https://ccforeveryone.com/guides/claude-code-limits-and-pricing |

**Design consequences of the refuted claim:** budget in *invocations*, cap episodes per run, detect throttling live (`EngineThrottled` → stop cleanly), rely on the crash-safe `processed:false` queue, and never promise completion times in onboarding copy.

---

## Prior-art patterns worth copying

| Pattern | Exemplar | Take for Cicada |
|---|---|---|
| **Subscription piggyback via plugin + hooks** | claude-mem (~91K stars): Claude Code plugin, five lifecycle hooks, compression on the user's existing auth, two-command install | The delivery vehicle. Package MCP + hooks + skills as a plugin | 
| **Dumb MCP server, smart client** | Basic Memory (57K monthly downloads): server makes zero LLM calls; the client's model is the intelligence | Cicada's MCP server already is this — keep it dumb |
| **Zero-LLM maximalism + scheduled dream cycle** | gbrain (~29K stars): regex wikilink cascade, zero model calls on write; background dedup/citation-repair | Push every possible Sleep stage to deterministic code → "structural Sleep"; independent convergence on markdown+git+MCP+scheduled consolidation validates the thesis |
| **Capture-surface breadth** | supermemory: extension + importers + plugin | Copy the breadth (importers exist; hooks + sessions importer next), reject the cloud processing |
| **Anti-patterns** | BYOK onboarding (OpenMemory, Letta) = funnel death; vendor cloud (Rewind/Limitless → Meta acquisition, service wind-down) = existential risk for lifelong archives; unauthenticated localhost API (claude-mem's HIGH-risk port-37777 audit) = must fix before distribution | Keys become the power-user branch; no hosted component in the default path; token-auth localhost:8000 is a launch blocker |
| **Platform built-ins as validation + foil** | ChatGPT "Dreaming" (async cross-chat consolidation, June 2026), Claude memory (all users, March 2026) | They validated asynchronous consolidation and defined the convenience bar; Cicada competes on ownership, provenance (git blame per belief), and cross-platform unification — the neutral layer above both vendors |

Sources: https://github.com/thedotmack/claude-mem · https://www.datacamp.com/tutorial/claude-mem-guide · https://www.augmentcode.com/learn/claude-mem-65k-stars · https://www.basicmemory.com/ · https://github.com/basicmachines-co/basic-memory · https://api.github.com/repos/garrytan/gbrain · https://weststack.io/blog/ai-memory-gbrain-knowledge-brain · https://supermemory.ai/docs/integrations/claude-code · https://www.cnbc.com/2025/12/05/meta-limitless-ai-wearable.html · https://x.com/mem0ai/article/2071990201531118063 · https://support.claude.com/en/articles/11817273-use-claude-s-chat-search-and-memory-to-build-on-previous-context

---

## The three candidate architectures

### A — Cicada Session-Native (Lens A: in-session first)

**Summary.** The chat session is Cicada's primary runtime. A Claude Code plugin delivers a SessionStart primer hook (pending-count + relevant nudges injected at turn zero), Stop/SessionEnd episode capture through a shared `episode_writer` service, a PreCompact flush, both skills, and MCP registration; a new `cicada_commit` MCP tool lets in-session librarian drains self-commit with `Cicada-Author` trailers. A keyless **structural Sleep** (`run(structural_only=True)`) runs nightly regardless of engine availability; a scheduled `claude -p` drain (MCP-only allowlist, batch cap, no `--bare`, env scrubbed of `ANTHROPIC_API_KEY`) is the batch floor; `llm_mode="agent"` is implemented and the four direct-litellm callsites are rerouted so `llm_mode="local"` becomes a complete Ollama rung. Full Codex mirror (skill port, `codex mcp add`, Automations or `codex exec`, sessions importer).

**Tradeoffs.** `claude -p` over Agent SDK (compliance over control); session-boundary capture over per-turn streaming (less noise, small crash-loss window narrowed by PreCompact); splitting Sleep into structural + agentic drain (graph never rots, but quality/freshness vary by day — made visible via trailers and `/status`); ChatGPT web stays export-import (freshness traded for zero public endpoint).

**Scores:** in-session **9** · feasibility **8** · onboarding **7** · maintenance **7** · ethos **9** → strongest overall base.

### B — Emergence: Zero-Key Cicada (Lens B: distribution first)

**Summary.** The .dmg-to-working-memory story with zero key prompts anywhere. Companion-app onboarding wizard replaces "paste your key" with a plan picker (`claude /login` / `codex login` — vendor OAuth, Cicada never sees the credential); a launchd runner (`com.cicada.sleep`, on-wake catch-up, `caffeinate`) sanitizes the env, resolves an engine (claude → codex → ollama → none), drains via headless librarian prompts with per-episode `mark_processed` (interruptible, resumable), then runs a deterministic pass that sweep-commits agentic writes. Distinctive contributions: the **ungated embedding default** (all-MiniLM class, ~90MB, no HF token; EmbeddingGemma as a one-click upgrade — the index is disposable, so the swap is a rebuild), installing **both** skills, and run-logs (`memory/sleep_runs/<date>.json`) surfaced in the dashboard.

**Tradeoffs.** Official-CLI subprocess over SDK (safest posture, coarser control); interruptibility over budget guarantees (forced by the refuted token claim — big backlogs converge over multiple nights); ungated embeddings trade retrieval quality for a genuinely promptless install; two schedulers (launchd + APScheduler) to reason about; SwiftUI wizard is the long pole but the CLI story works before it ships.

**Scores:** in-session **7** · feasibility **8** · onboarding **9** · maintenance **6** · ethos **8** → best onboarding thinking, heaviest moving-parts count.

### C — Cicada Engine Ladder (Lens C: provider parity + graceful degradation)

**Summary.** Promote the dormant provider factory into the **single mandatory LLM seam** (no service imports litellm again) and add an `api/services/engines/` layer: `claude_cli`, `codex_cli`, `local_ollama`, `byok`, with a probing resolver and per-stage policy table. Subscription engines run **stage-level batch jobs** (~5–8 agent-shaped invocations per cycle — extraction chunks, one disambiguation job, one consolidation job — schema-validated by the Python pipeline) rather than hundreds of shimmed completions; the proven **driver-style** librarian session ships first. `run_structural()` always runs. The local rung gets a **merge-suggestion valve** (low-confidence Stage-2 verdicts become human-confirmed inbox items, never auto-merges), a JSON-Schema-constrained Ollama path, and a model bump. Free-tier CLIs are excluded from the default ladder (2026's rug-pull record + training-ToS). Explicitly rejected: an OpenAI-compatible proxy over the CLIs (invites the prohibited token-reuse pattern) and dropping litellm (discards tested routing).

**Tradeoffs.** Batch jobs cost real refactor of S1/S2/S3 but are the only shape simultaneously cheap, fast, and ToS-defensible; driver-first accepts temporary stage-coverage limits (no Stage-4 patterns) backed by the 988-episode proof; `/ask` prefers low-latency rungs over subscription cold-starts; in-backend scheduler only (simpler, but consolidation requires the backend up).

**Scores:** in-session **6** · feasibility **7** · onboarding **6** · maintenance **7** · ethos **9** → cleanest engine architecture, weakest session experience.

### Score summary

| Dimension | A Session-Native | B Emergence | C Engine Ladder |
|---|---|---|---|
| In-session usefulness | **9** | 7 | 6 |
| Feasibility today | **8** | **8** | 7 |
| Onboarding friction | 7 | **9** | 6 |
| Maintenance burden | 7 | 6 | **7** |
| Local-first ethos | **9** | 8 | **9** |
| **Total** | **40** | 38 | 35 |

---

## Recommended architecture: the Session-Native Engine Ladder

**Base: Design A. Grafts: C's engine seam + ladder + batch phasing + merge-suggestion valve; B's wizard, ungated embeddings, launchd runner discipline, and run-logs.**

### Explicit conflict resolutions

1. **Scheduler:** launchd owns the nightly trigger (B) — `StartCalendarInterval` fires missed jobs on wake, survives backend-down nights, wraps work in `caffeinate -i`. The in-backend APScheduler (C's preference) is *demoted, not removed*: it invokes the same idempotent runner entrypoint as a fallback, and `PUT /sleep/schedule` writes one config both read.
2. **Subscription engine style:** C's two-style split, phased — **driver-style ships first** (one `claude -p` session running the librarian loop via MCP; proven at 988 episodes), **batch StageJobs are Phase 4** (full 5-stage parity, schema-validated, ~5–8 invocations/cycle). `CICADA_AGENT_STYLE=driver|batch`.
3. **Agent SDK vs `claude -p`:** `claude -p` only. The verified claims themselves conflict (SDK subscription auth "available" per the support article vs the Feb-2026 "OAuth only in Claude Code and claude.ai" clarification); the official binary is the only posture defensible under both readings. Runner asserts: no `ANTHROPIC_API_KEY` in env, never `--bare`, invocation flags pinned, doctor watches for the bare-by-default flip.
4. **Embeddings:** B wins — ungated all-MiniLM-class default (no HF token anywhere in onboarding), EmbeddingGemma as a one-click quality upgrade in app settings (disposable index → cheap rebuild). This removes the last credential from the default flow.
5. **Committing agentic writes:** both A and B/C mechanisms — `cicada_commit` for in-session self-commit with live provenance, **and** the structural-sleep sweep-commit as the safety net for anything left uncommitted.
6. **`/ask`:** C's latency policy (ollama → byok → subscription shim, citation-only degrade preserved); inside agent sessions, `cicada_ask`'s description steers to `cicada_recall` + host-model synthesis.
7. **Free-tier CLIs:** outside the default ladder (C's call) — opt-in `CICADA_ENGINE_EXTRA_CLI` booster only.
8. **Security:** bearer-token on localhost:8000 is a **launch blocker** before the plugin, the tunnel, or any distribution (unanimous).

### Components (file map)

| Component | Files | Effort |
|---|---|---|
| **P0 Security + hygiene**: loopback bind + generated bearer token honored by `APIClient.swift` and `mcp/server.py`; keyless-first `install.sh` + `.env.example` rewrite (no key prompts; BYOK behind `--advanced`); both skills installed; doctor expansion (engine probes, auth mode, stray-key warning, launchd jobs, hooks, queue depth) | `api/main.py`, `install.sh`, `api/.env.example`, `scripts/doctor.sh`, `app/.../APIClient.swift` | S |
| **P1 Structural Sleep**: `run_structural()` — decay math, wikilink/media/claim edges, hub/_index regen, inbox generation, sqlite-vec rebuild, git sweep-commit of agentic writes with engine `Cicada-Author:` trailers; scheduled always | `api/services/sleep_cycle.py`, `git_service.py`, `sleep_scheduler.py` | M |
| **P1 Engine layer**: `engines/` package — `base.py` (Engine protocol + StageJob contracts), `claude_cli.py` (probe, `run_driver()`, later `run_job()`; env scrub; `EngineThrottled`), `codex_cli.py`, `local_ollama.py` (json_schema-constrained, model bump to a current small model), `byok.py`, `resolver.py` ladder; `llm_mode` grows `auto` (fresh-install default) and implements `agent` | new `api/services/engines/`, `api/config.py`, `api/services/providers.py` | M |
| **P1 Nightly runner**: `scripts/sleep_runner.sh` + `com.cicada.sleep` plist — env sanitize → queue check → resolve engine → drain (driver-style, episode cap, stop-on-throttle) → structural pass → `memory/sleep_runs/<date>.json` | new scripts + plist; `GET /sleep/history`, `GET /status` gain `unprocessed_episode_count`, `last_sleep_engine`, `next_scheduled_run` | M |
| **P2 Claude Code plugin**: SessionStart primer (deterministic: pending count, relevant inbox items, active bank), Stop/SessionEnd capture via new shared `episode_writer.py` (refactored out of `mcp/server.py`; origin `claude-code-hook`; content-hash idempotent; errors exit 0), PreCompact flush; ships skills + MCP registration | new `packaging/claude-plugin/`, new `api/services/episode_writer.py` | M |
| **P2 Librarian upgrade**: `cicada_commit` MCP tool (→ `git_service.build_commit_message`, optional `session_ref` for G48); skill edit: commit after `mark_processed` | `mcp/server.py`, `skills/cicada-librarian/SKILL.md`, `agentic_write.py` (thread `session_ref`) | S |
| **P3 Codex/ChatGPT mirror**: Codex-dialect skill (`packaging/codex/`), memory-repo AGENTS.md stanza, `codex mcp add` registration (`required=true`), Automation template or `codex exec` runner branch, `codex_sessions_importer.py` (defensive parsing, origin `codex-session`), training-opt-out onboarding note; web = existing export importer, opt-in read-only tunnel (Pro-verified only) | new files + `api/routers/conversations.py` | M |
| **P4 Seam completion + batch**: reroute Stage-1, Stage-2 judge, `/ask`, link-enrichment through `resolve_llm_fn`; batch StageJobs for S1/S2/S3 (+ dedup/links); Stage-2 merge-suggestion valve for the local rung | `entity_extractor.py`, `entity_resolver.py`, `ask_service.py`, `link_enrichment.py`, `conflict_resolver.py`, `dedup_sweep.py` | M/L |
| **P5 Surfaces + wizard**: SwiftUI plan-picker onboarding (OAuth handoff, schedule picker with honest no-token-numbers copy, doctor checklist), dashboard engine/queue surfacing; `.mcpb` Desktop Extension; opt-in Cloudflare-Tunnel remote connector (behind P0 auth) | `app/CicadaApp/`, new `packaging/mcpb/` | L |

### Data flow (Claude persona; Codex persona is isomorphic)

```
[Claude Code session]
  SessionStart hook ─▶ primer: pending count + relevant nudges (inbox_service, keyless)
  conversation      ─▶ cicada_recall / recall_detail / open_hub (keyless, local sqlite-vec)
  "remember this"   ─▶ cicada_save_episode / cicada_write_claim (librarian skill, host model pays)
  Stop/SessionEnd   ─▶ episode_writer ─▶ memory/episodes/ (processed:false)
  session-end drain ─▶ librarian loop ─▶ write_claim×N ─▶ mark_processed ─▶ cicada_commit

[Nightly, launchd com.cicada.sleep, on-wake catch-up]
  sleep_runner.sh:
    env scrub ▸ queue check ▸ resolve engine (ladder probe)
    ├─ claude -p driver drain (cap N, MCP-only allowlist, stop on throttle)   [rung 1]
    ├─ codex exec drain (ChatGPT persona)                                     [rung 1]
    ├─ full local 5-stage cycle, llm_mode=local (after P4 seam completion)    [rung 2]
    └─ none: queue-depth nudge into inbox                                     [rung 4]
    then ALWAYS: run_structural() → decay ▸ edges ▸ hubs ▸ inbox ▸ index ▸ git commit
    then: memory/sleep_runs/<date>.json → /sleep/history + dashboard
```

### The degradation ladder

| Rung | Engine | Quality | Breaks when | Visible as |
|---|---|---|---|---|
| side | Opportunistic librarian (user's own session) | Frontier + live context (best disambiguation possible) | User opens no sessions | `Cicada-Author: <session model>` |
| 1 | Subscription CLI (`claude -p` / `codex exec`) | Frontier, batch | Throttled, unauthenticated, policy change | `Cicada-Author: claude-code` / `codex`; `engine_used` in run log |
| 2 | Local Ollama (`llm_mode=local`, schema-constrained) | Small-model; Stage-2 valved to merge-suggestions | Ollama down, model not pulled, <8GB free RAM | `Cicada-Author: ollama/<model>` |
| 3 | BYOK (litellm + key) | Configurable | No key (never prompted for) | `Cicada-Author: <model id>` |
| 4 | Skip-with-queue | — (capture + recall unaffected) | Backlog weeks-deep → nudge fires | Queue depth in `/status` + inbox nudge |
| floor | Structural Sleep | Deterministic | Never (pure Python) | Nightly commit, always |

Coordination contract between all rungs and the opportunistic path is the existing `processed: false` flag — already proven to compose.

### Onboarding — Claude-plan user (Pro/Max)

1. Download `Cicada.dmg` → drag → open. First launch: memory tree + git init, backend starts (existing `Process()` + launchd).
2. Wizard: **"Which AI plan do you have?"** → `[Claude Pro/Max] [ChatGPT Plus/Pro] [Neither — run fully local] [Advanced: API key]`. This screen *is* the replacement for "paste your key."
3. Claude branch: detect `claude` CLI (offer install) → **"Sign in with your Claude plan"** runs `claude /login` (Anthropic's own browser OAuth; Cicada never sees the credential).
4. Wizard installs the plugin (`/plugin marketplace add rorosaga/cicada` → `/plugin install cicada`): MCP registration + both skills + all hooks in one step. `.env` written: `CICADA_LLM_MODE=auto`, `CICADA_EMBEDDING_MODE=local` (ungated model downloads in background; recall works meanwhile via keyword/hub cold-start fallback).
5. **"When should Cicada sleep?"** → installs `com.cicada.sleep-structural` (03:00) + `com.cicada.sleep-agent` (03:30, created only after verifying login state; warns if `ANTHROPIC_API_KEY` is in the login environment). Honest copy: *"Runs on your Claude plan. If your Mac is asleep, it runs on next wake. If your plan is rate-limited, Cicada stops and resumes the next night — nothing is lost."* (No token numbers — they aren't published.)
6. Optional: import Claude/ChatGPT export ZIPs (existing `/banks/{name}/import`), bookmarks, Telegram. Doctor checklist goes green. Optional: `.mcpb` for Claude Desktop; opt-in tunnel for claude.ai web.

### Onboarding — ChatGPT-plan user (Plus/Pro)

1–2. Same .dmg + wizard; picks ChatGPT.
3. Detect `codex` CLI → `codex login` (device-auth for headless boxes). `codex mcp add cicada -- python3 mcp/server.py` (shared `~/.codex/config.toml` also lights up the ChatGPT desktop app); Codex-dialect skills → `~/.codex/skills/`; AGENTS.md stanza written into the memory repo.
4. Scheduling choice: **Codex app Automation** from a provided template (nightly RRULE, workspace-write, review-queue output — matches "agent proposes, user disposes") or the launchd `codex exec` branch.
5. Enable the `~/.codex/sessions` importer (passive capture of every Codex-surface conversation). **Privacy step: disable "Improve the model for everyone."**
6. Backfill: chatgpt.com export → importer (expectation set: export can take days). Optional read-only web connector (Pro-verified; Plus unconfirmed). No model ids pinned anywhere (GPT-5.4* leaves ChatGPT-auth Codex 2026-08-31).

**Local-only user:** wizard installs/pulls Ollama + a RAM-appropriate small model, sets `CICADA_LLM_MODE=local`; same schedule, same dashboard, zero network. **Every path shares:** capture, recall, the trust-gated write path, structural Sleep, and git provenance — all already keyless.

---

## Phased build plan

| Phase | Contents | Effort | Exit criterion |
|---|---|---|---|
| **0** | localhost bearer token; install.sh/.env.example keyless rewrite; both skills installed; doctor expansion | **S** (~3–4 days) | No key prompt anywhere; backend authenticated; doctor green |
| **1** | Structural Sleep; engines package (probes + resolver + driver-style claude_cli); launchd runner + run logs; `/status` queue/engine fields | **M** (~1.5–2 wks) | Claude-plan user gets scheduled zero-key consolidation; graph never rots; agentic writes committed+indexed nightly |
| **2** | Claude Code plugin (primer, capture, PreCompact) via `episode_writer` refactor; `cicada_commit` + skill edit | **M** (~1 wk) | Passive capture + proactive primer in every Claude Code session; in-session drains self-commit |
| **3** | Codex mirror: skill port, MCP registration, Automation template / `codex exec` branch, sessions importer, privacy step | **M** (~1–1.5 wks incl. hands-on validation of Automation-MCP and desktop surfaces) | ChatGPT-plan parity on Codex surfaces |
| **4** | Seam completion (4 callsites) + batch StageJobs S1/S2/S3 + Stage-2 merge-suggestion valve + Ollama json_schema tightening/model bump | **M/L** (~1.5–2 wks) | `llm_mode=local` is one-switch complete; subscription cycle = ~5–8 schema-validated invocations with full 5-stage parity |
| **5** | SwiftUI wizard + dashboard engine/queue surfaces; `.mcpb`; opt-in tunnel | **L** (~2 wks) | .dmg-first-launch persona fully served |

Total ≈ 5–7 focused solo weeks. No new infrastructure, databases, or hosted services anywhere; litellm and all existing tests survive; `llm_mode=byok` behavior stays byte-identical.

---

## Risks & open questions

**ToS / policy (the big one).**
- Subscription OAuth is confirmed for `claude -p` today, but the Feb 2026 clarification limits OAuth tokens to Claude Code and claude.ai, docs recommend `--bare` + API key for scripted calls, and `--bare` is slated to become the `-p` default — which would silently break OAuth drains. Mitigations: official binary only, pinned invocation flags, doctor check for the flip, Ollama floor one config away. **Open question:** whether a nightly personal batch is "ordinary, individual usage of Claude Code" — plausibly yes, not explicitly adjudicated.
- The verified claims themselves conflict on Agent SDK + OAuth (support article says available; legal clarification says not permitted). Resolved conservatively (`claude -p` only), but **re-verify before ever considering an SDK driver**.
- The June 15 billing-split pause could un-pause with notice (Anthropic says reworked, not cancelled) — watch https://support.claude.com/en/articles/15036540. The ladder absorbs it; costs would become visible via `engine_used`.
- OpenAI: ChatGPT-account auth for non-interactive runs is documented but conditioned (trusted private infra, one machine per `auth.json`); policy drift is possible.

**Limits.** No token-denominated budgets exist (verified refuted); weekly caps are real. Design response: invocation budgeting, live throttle detection, mid-cycle degradation, resumable queue. Worst case is multi-night convergence on big backlogs — surfaced honestly, never silent.

**Env footgun.** A stray `ANTHROPIC_API_KEY` silently bills the API in `-p` mode (confirmed; issue #37686). Runner unsets it; doctor warns.

**Codex unknowns (hands-on validation required before Phase 3 exit).** MCP-tool use inside Codex app Automations (implied by shared config, undocumented); which ChatGPT-desktop chat surfaces invoke local stdio MCP; Plus-tier availability of desktop MCP and web developer-mode read access; `~/.codex/sessions` JSONL is community-documented and unversioned (defensive parsing, importer failure non-fatal); GPT-5.4* removal 2026-08-31 (no pinned models).

**Coverage.** Driver-style replaces Stage 1 + Stage-3-lite only — Stage-4 cross-session pattern detection lands with the weekly batch pass (Phase 4) or on local/BYOK rungs until then. Hooks fire only in local Claude Code: no auto-capture from claude.ai web/mobile without the opt-in tunnel; ChatGPT web writes are Business+-only.

**Quality.** Local-rung Stage-2 disambiguation is the weak stage — contained by the merge-suggestion valve (mis-merges become human-confirmed inbox items). Headless drains can't ask the user — ambiguity follows the existing `ambiguous_subject` contract into the inbox, never a guess.

**Privacy.** ChatGPT-plan users must disable "Improve the model for everyone" or memory content may train models (onboarding step). The tunnel option moves a local-first system's front door onto the internet — opt-in only, behind P0 auth.

**Security.** Shipping the plugin or any tunnel before the localhost token repeats claude-mem's audited mistake. Launch blocker.

### Load-bearing claims NOT verified (only 5 were checked — re-confirm these before relying on them)

1. Claude Code **hooks**: existence/semantics of SessionStart `additionalContext`, transcript path in Stop/SessionEnd payloads, PreCompact hook — the entire P2 capture design rests on these.
2. Claude Code **plugin marketplace** mechanics (`/plugin marketplace add` / `/plugin install`) as a distribution vehicle.
3. **All Codex-side claims**: plan-included usage, `codex exec` flags (`--output-schema`, sandbox modes), `codex mcp add`, skills format, CI/CD account-auth guide, Automations — researched against official URLs this cycle but not independently verified.
4. ChatGPT **desktop app local stdio MCP** and which surfaces invoke it; **Plus-tier** web developer-mode read access.
5. `.mcpb` **Desktop Extensions** current state and claude.ai **remote MCP connector** plan gating.
6. `~/.codex/sessions` JSONL format (community-documented only).
7. Ollama structured-outputs grammar constraint via litellm, current small-model quality/throughput figures (community benchmarks, ±30%).
8. Prior-art stats (claude-mem/gbrain star counts, platform-memory feature details) — third-party sources.

---

## Sources

**Anthropic official:** https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan · https://support.claude.com/en/articles/11145838-use-claude-code-with-your-pro-or-max-plan · https://support.claude.com/en/articles/11049741-what-is-the-max-plan · https://code.claude.com/docs/en/authentication · https://code.claude.com/docs/en/headless · https://code.claude.com/docs/en/cli-reference · https://code.claude.com/docs/en/legal-and-compliance · https://www.anthropic.com/legal/consumer-terms · https://support.claude.com/en/articles/9762155-claude-code-hooks · https://support.claude.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop · https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp · https://support.claude.com/en/articles/11817273-use-claude-s-chat-search-and-memory-to-build-on-previous-context · https://support.claude.com/en/articles/14552646-troubleshoot-claude-code-installation-and-authentication

**Anthropic-adjacent reporting:** https://thenewstack.io/anthropic-pauses-claude-agent-sdk-subscription-change/ · https://zed.dev/blog/anthropic-subscription-changes · https://devops.com/anthropic-hits-pause-on-claude-agent-sdk-billing-change-for-now/ · https://siliconangle.com/2026/05/14/anthropic-announces-programmatic-credit-pool-agentic-tool-use-rises/ · https://www.theregister.com/software/2026/02/20/anthropic-clarifies-ban-on-third-party-tool-access-to-claude/5014546 · https://techcrunch.com/2025/07/28/anthropic-unveils-new-rate-limits-to-curb-claude-code-power-users/ · https://github.com/anthropics/claude-code/issues/43333 · https://github.com/anthropics/claude-code/issues/37686 · https://explainx.ai/blog/claude-usage-limits-2026-timeline-explained · https://ccforeveryone.com/guides/claude-code-limits-and-pricing

**OpenAI official:** https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan · https://developers.openai.com/codex/noninteractive · https://developers.openai.com/codex/mcp · https://developers.openai.com/codex/skills · https://developers.openai.com/codex/auth · https://developers.openai.com/codex/auth/ci-cd-auth · https://developers.openai.com/codex/guides/agents-md · https://openai.com/index/introducing-the-codex-app/ · https://learn.chatgpt.com/docs/automations · https://learn.chatgpt.com/docs/extend/mcp · https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt · https://developers.openai.com/api/docs/guides/secure-mcp-tunnels · https://github.com/openai/tunnel-client · https://help.openai.com/en/articles/10291617-tasks-in-chatgpt · https://help.openai.com/en/articles/11752874-chatgpt-agent · https://help.openai.com/en/articles/7260999-exporting-your-chatgpt-history-and-data · https://help.openai.com/en/articles/11487775-apps-in-chatgpt · https://openai.com/policies/terms-of-use/ · https://github.com/openai/codex/discussions/3827 · https://github.com/openai/skills

**Local/keyless:** https://ollama.com/library/qwen3.5 · https://ai.google.dev/gemma/docs/core/model_card_4 · https://docs.ollama.com/capabilities/structured-outputs · https://ollama.com/blog/mlx · https://docs.litellm.ai/docs/providers/ollama · https://llmcheck.net/benchmarks · https://developers.googleblog.com/an-important-update-transitioning-gemini-cli-to-antigravity-cli/ · https://github.com/QwenLM/qwen-code/issues/3203 · https://github.com/features/copilot/plans · https://developers.google.com/gemini-code-assist/resources/privacy-notice-gemini-code-assist-individuals

**Prior art:** https://github.com/thedotmack/claude-mem · https://www.datacamp.com/tutorial/claude-mem-guide · https://www.augmentcode.com/learn/claude-mem-65k-stars · https://www.basicmemory.com/ · https://github.com/basicmachines-co/basic-memory · https://api.github.com/repos/garrytan/gbrain · https://weststack.io/blog/ai-memory-gbrain-knowledge-brain · https://docs.mem0.ai/integrations/claude-code · https://mem0.ai/blog/introducing-openmemory-mcp · https://supermemory.ai/pricing/ · https://supermemory.ai/docs/integrations/claude-code · https://github.com/plastic-labs/honcho · https://www.letta.com/ · https://www.cnbc.com/2025/12/05/meta-limitless-ai-wearable.html · https://github.com/msdanyg/smart-connections-mcp · https://x.com/mem0ai/article/2071990201531118063 · https://blog.memoryplugin.com/how-claude-memory-works/

**Repo grounding (all paths under `/Users/rorosaga/Documents/roros_lab/cicada`):** `api/config.py` · `api/services/providers.py` · `api/services/entity_extractor.py` · `api/services/entity_resolver.py` · `api/services/conflict_resolver.py` · `api/services/skill_extractor.py` · `api/services/link_enrichment.py` · `api/services/ask_service.py` · `api/services/dedup_sweep.py` · `api/services/source_rewrite.py` · `api/services/sleep_cycle.py` · `api/services/sleep_scheduler.py` · `api/services/agentic_write.py` · `api/services/claim_pipeline.py` · `api/services/git_service.py` · `api/services/vector_index.py` · `api/services/telegram_capture.py` · `mcp/server.py` · `skills/cicada-librarian/SKILL.md` · `SKILL.md` · `install.sh` · `scripts/doctor.sh` · `docs/goals/memory-evolution.md` · `api/tests/test_local_llm.py`
