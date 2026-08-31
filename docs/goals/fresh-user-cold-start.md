# The fresh-user cold start & always-on capture (2026-08-31)

Produced by the fresh-user/always-on workflow (3 investigators + synthesis). Grounds **G76**
and re-prioritizes **G74(a)** as the single unlock. Companion to
[`subscription-first-portability.md`](subscription-first-portability.md) (G49).

# The fresh Claude-Max-only user's first hour

Persona: has Claude Code + a Max plan, zero API keys, zero credits, months of claude.ai/Desktop history and a large `~/.claude/projects/` corpus. Each step is marked **TODAY-WORKS**, **NEEDS-G74**, or **NEEDS-NEW** with the exact gap.

1. **0:00 — Find Cicada, paste the install prompt. NEEDS-NEW.** There is no `install.md` anywhere in the repo and no README setup prompt; README's Requirements instead demand "an OpenAI API key for embeddings and the default Sleep-cycle model" (README.md:130) — the exact funnel-death the G49 research documents. A Max-plan user reads "not for me" before anything runs. Gap: the repo-root `install.md` + README "Install via Claude Code" section (drafted below). Every feeder asset already exists: idempotent `install.sh`, `doctor.sh` with per-check remediation and exit-code=failure-count, and the 7-agent registration table in `AgentSetupCatalog` (ConnectView.swift:37-183, currently locked inside compiled Swift).

2. **0:02 — Agent clones to a durable path and runs `./install.sh`. TODAY-WORKS, two burrs.** Verified idempotent and non-interactive-safe (key prompts skipped when stdin isn't a TTY): preflight uv+git (:119-136, aborts with the printed uv one-liner if missing — minor friction for a non-dev), uv-sync venv (:138-150), memory tree + git init (:152-171). Burrs needing NEEDS-NEW (small): on a TTY it interactively prompts for OPENAI_API_KEY and ANTHROPIC_API_KEY (install.sh:239-240) and always scaffolds `CICADA_EMBEDDING_MODE=openai` (:214) against the code default "local" (api/config.py:59); the `uv sync --extra local` hint (:246-248) is stale — sentence-transformers is a main dep (api/pyproject.toml:18).

3. **0:05 — MCP registration + launchd backend + bearer token. TODAY-WORKS.** `claude mcp add cicada` (install.sh:252-277, manual JSON printed if the CLI is absent), launchd `com.cicada.backend` with KeepAlive + /healthz wait (:279-333), token at `~/.cicada/api_token`.

4. **0:06 — Skills. NEEDS-NEW.** `install.sh --skill` copies only the repo-root recall SKILL.md (:336-343); `grep librarian` across install.sh, Makefile, and ConnectView.swift returns zero hits. The one consolidation path that works on a Max plan today — the cicada-librarian drain loop, proven at 988 episodes → 442 claims → 74 entities with zero keys — is installed by nothing.

5. **0:08 — `make doctor`. TODAY-WORKS, two permanent false reds.** For this persona the `_index.md` check can never pass (requires a successful full cycle — impossible with no engine) and check #5 greps `memory/leann/*.meta.json` (doctor.sh:78), files the sqlite-vec indexer never writes (it writes `vector_index.db` at the memory root, vector_index.py:35,94). An agent told to "loop until doctor is green" can never finish. NEEDS-NEW: fix check #5, make the index checks first-cycle-conditional.

6. **0:10 — Request the claude.ai export. TODAY-WORKS (genuinely human step).** ConnectView already honestly tells claude.ai/web users to use export-import (:289-292); G64 ships the deep-link button + numbered steps. The ZIP arrives by email — the hour's one real async wait.

7. **0:20 — Import the export ZIP. TODAY-WORKS, minor silent loss.** One Anthropic parser family covers web AND Desktop (Desktop has no separate format); import is additive, backdated, delta-aware by source_id (G20). Caveat, NEEDS-NEW (tiny): `_parse_zip` extracts exactly ONE file per ZIP — MyActivity.html then conversations.json priority (conversations.py:668-680) — so `memories.json` (free entity-seed data Cicada's own parser exists for, conversations.py:305-338) and `projects.json` are silently dropped unless uploaded individually, and nothing tells the user to.

8. **0:20 — Claude Code history. NEEDS-NEW (silent corpus loss).** `~/.claude/projects/*.jsonl` — the persona's largest, richest corpus — has zero import path: the only touches are the Resume-button existence probe (session_stats.py:72) and live-session stamping (mcp/server.py:121); G48 explicitly says "no backfill" (memory-evolution.md:531). The user assumes it was imported; it wasn't, and no UI acknowledges the gap. Fix: a transcript importer reusing the G20 delta-staging machinery, backdated episodes with session_id provenance.

9. **0:25 — Connections page shows "Claude Max · Connected". TODAY-WORKS — and makes step 10 worse.** The G50 claude_cli adapter probes `claude auth status --json` and drives login (claude_cli.py:48-57). The app implies the plan is usable; nothing consumes it.

10. **0:30 — POST /sleep/trigger. NEEDS-G74 — THE WALL.** Verified hands-on: the run hard-aborts at Stage 1 with "Stage 1 extracted nothing — all episodes failed (check model id / API credits). Queue left intact for retry." (sleep_cycle.py:206-219; per-episode auth failures requeue, entity_extractor.py:367-379), surfaced as a red banner (SleepView.swift:59-60). The message blames credits the user was never going to have. The single missing piece: `llm_mode="agent"` is reserved-but-unimplemented (api/config.py:101-105) and `providers.resolve_llm_fn` contains zero "agent" handling (providers.py:186) — while the seam is otherwise COMPLETE (all five stages + /ask route through it, G51). One `claude -p` engine branch behind that one seam, defaulting to `llm_mode=auto` when a plan is Connected, lights up everything.

11. **0:31 — Empty graph, growing queue. NEEDS-G74.** No entities (they only exist post-consolidation), no `hubs/_index.md` (Stage 5.6 of a successful cycle only, sleep_cycle.py:335-340), no vector index (post-Stage-5, :392-425). And recall was silently keyword-only all along: the keyless local default is HF-gated EmbeddingGemma-300m; without HF_TOKEN every embed fails soft and vector search returns [] (vector_index.py:234-237) with no user-visible warning.

12. **0:35 — The rescue path exists but is undiscoverable. NEEDS-NEW.** The librarian drain (cicada_pending → write_claim → mark_processed) would let their Max plan consolidate the backlog today, but: nothing installs the skill (step 4), nothing schedules it, the Sleep error doesn't point to it, and even a manual drain leaves writes uncommitted and unindexed (agentic_write.py has zero git/index calls; the zero-episode Sleep path skips commit/index/hubs, sleep_cycle.py:182-191).

**Bottom line:** ship G74(a) + the G49-P0 install fixes + `install.md`, and the hour becomes: paste prompt (min 0) → installer + doctor green (min 8) → import ZIP (min 20) → "Run Sleep" on the connected plan → graph appears (min ~40). Today the same user hits a dead product at minute 30 with an error telling them to buy credits.

## The README install-prompt section (draft, ready to ship)

Verbatim draft for README.md (place directly after the intro blurb, replacing the current manual Setup section's top; browser-harness anatomy — two-beat prompt, all intelligence in a versioned `install.md`):

---

## Install via Claude Code

One pasted prompt. No API keys — Cicada runs on the Claude plan you already have.

Paste this into Claude Code:

```
Set up https://github.com/rorosaga/cicada for me.

Read `install.md` and follow the steps: clone Cicada to a durable path, run its
installer, register the Cicada MCP server with this agent, install both Cicada
skills, and register the session-capture hooks (SessionEnd + PreCompact). Then
run `make doctor` and fix anything red until it exits clean. Finish by saving
one memory about me and recalling it so I can see Cicada working, and report
back what you set up.
```

Using Codex instead? Same prompt, one clause changed:

```
Set up https://github.com/rorosaga/cicada for me. Read `install.md` and follow the Codex steps — same flow, but register the MCP server, skills, and hooks with Codex.
```

The prompt is deliberately dumb: every command, path rule, per-agent branch, key decision, and troubleshooting case lives in [`install.md`](install.md), versioned next to the code — so the prompt never drifts. Your agent will:

- clone to a stable location (`~/Developer/cicada` by default, never `/tmp`) or reuse an existing checkout,
- run `./install.sh` — idempotent and safe to re-run; it creates the venv, memory tree, `.env`, backend service, and auth token,
- register the `cicada` MCP server and install the `cicada` (recall) and `cicada-librarian` (consolidation) skills,
- add lightweight end-of-session capture hooks — they post a session *pointer* to your local backend, never transcript content,
- verify with `make doctor` (each failing check prints its own fix) and demo a save + recall you can see.

Two things only you can do, and the agent will ask: approve the hook registration, and (optionally) paste an embeddings key if you want cloud embeddings — blank is fine, the local default works.

This is one-time. Your agent never repeats install steps during normal memory work.

---

Note on the "Setup prompt" heading style: browser-harness ships ONE prompt labelled "Paste into Claude Code or Codex" and branches per-agent inside install.md; the Codex twin above changes only the final clause, never the structure. Prerequisites before this section can ship honestly: G49-P0 (kill install.sh's TTY key prompts, scaffold `CICADA_EMBEDDING_MODE=local`, rewrite README Requirements), the doctor.sh check-#5 fix (an agent must be able to reach green), and `--skill` installing both skills.

## Always-on capture design

# Always-on capture design: content-on-signal, pointers-by-hook

**The rule:** curated episode content is written by the agent *when something worth remembering happens* (a decision, preference, fact, plan); a deterministic hook guarantees *no session is ever invisible* by posting a cheap pointer at session end. Raw transcript content never enters a bank silently.

## Why never silent full-transcript ingestion

1. **It violates shipped design, not just taste.** The G48 provenance spec states the invariant explicitly: no transcript content ever enters a bank, an API response, a log line, or a telemetry event (2026-08-31-conversation-provenance-design.md ~line 116).
2. **The mass is measured and decisive:** the curated store is 2.4 MB / 117 episodes; this one project's transcript dir is 238 MB (741 MB across `~/.claude/projects`, 73 MB `~/.codex/sessions`). Auto-dumping is ~100–300× the curated input mass, dominated by tool output — file reads, command output, secrets-bearing terminal text.
3. **It lands on an engineless Sleep** (G74): every byte captured today joins an unprocessable `processed: false` backlog. Pointers are drainable later; dumps are debt.

Derived content is fine: at consolidation time a G74(b) agent may read a pointed-to transcript *transiently* and write distilled claims through the trust-gated `write_claim` path — distillate enters the bank, raw never does.

## Claude Code stack (ships as the G49 plugin: hooks + both skills + MCP registration)

1. **G75 handshake (read-side contract):** return `instructions` from MCP `initialize` — the interaction contract ("check nudges at start; save episodes AS you learn decisions/facts/preferences, not just at session end; `cicada_write_claim` with `sources:` for looked-up facts") plus the G53 state snippet; identical text via a `cicada_handshake` tool for harnesses that ignore the field.
2. **Skill DESCRIPTION rewrite (the in-flow content lever):** descriptions are the only always-loaded text, so the mid-session standing instruction must live there, phrased as a TRIGGER block (the claude-api-skill pattern): "whenever the user states a decision, preference, fact, or plan → `cicada_save_episode` before moving on; whenever you look up a fact for them → `cicada_write_claim` with sources." Today both skills phrase capture as end-of-session/on-request events — the body-only imperatives never fire mid-flow.
3. **SessionEnd hook (the deterministic pointer net):** exec-form command, explicit ~10 s timeout (SessionEnd shares a 1.5 s budget raised to the largest configured per-hook timeout, capped 60 s), always exit 0: `curl --max-time 5` POST to a **new bearer-authed `POST /capture/session-end`** with `{session_id, transcript_path, cwd, reason}` — a pointer, NO content. Server-side, idempotent on (session_id, reason): if MCP episodes already carry that session_id (G48 stamps it from `CLAUDE_CODE_SESSION_ID`), the marker is pure provenance closure; if none do, stage a lightweight episode pointer and flag the conversation **"uncaptured"** in Activity ▸ Conversations — visible silence, queued for G74(b) agent-consolidation.
4. **PreCompact hook:** same POST, `reason=compact` — context about to be destroyed is the one moment worth flushing.
5. **SessionStart hook:** the G49 primer (pending inbox count + G53 state dict via `additionalContext`) — the read-side of effortlessness.
6. **Stop hooks deliberately excluded from capture** (despite being available): Stop fires every turn — volume without judgment; the skill trigger is the per-turn lever, the SessionEnd pointer the guarantee.

## Codex realistic subset (near-parity — supersedes the portability doc's "notify-only" assumption)

Codex now ships full lifecycle hooks (SessionStart/SessionEnd/PreCompact et al., payloads include session_id + transcript_path, `~/.codex/hooks.json` or config.toml, async supported): mirror the SessionEnd/PreCompact pointer hooks against the same endpoint. Differences to respect: SessionEnd is synchronous and advisory-only; non-managed hooks require the explicit `/hooks` trust step — onboarding MUST include it or auto-capture silently never runs. The always-on contract goes in `~/.codex/AGENTS.md` (32 KiB budget, auto-loaded every session) since `initialize.instructions` injection is unverified; port the librarian skill to `~/.codex/skills/cicada/`; add a `~/.codex/sessions` backfill importer (defensive parsing — unversioned format; origin `codex-session`) for whatever the skill missed.

## Other MCP harnesses (Cursor, Windsurf, Desktop…)

Handshake + skill only. Minted `ses_` fallback ids (mcp/server.py:82-86) keep conversation grouping working, but there is no pointer safety net — state this honestly in the per-harness capability notes G75 already plans to key off `clientInfo`.

## Hands-on checks required before building (all flagged NOT-VERIFIED)

- Hook-payload `session_id` byte-identical to the `CLAUDE_CODE_SESSION_ID` env var the MCP child receives (the join key; assumed yes, verify once).
- Whether Claude Code / Codex actually inject `initialize.instructions` into model context — the value of G75's outbound half; fallbacks already planned.
- Codex hooks end-to-end: the `/hooks` trust flow, advisory SessionEnd semantics, project-level hooks.json trust.
- SessionStart `hookSpecificOutput.additionalContext` exact shape (the repo's own portability checklist still flags it).
