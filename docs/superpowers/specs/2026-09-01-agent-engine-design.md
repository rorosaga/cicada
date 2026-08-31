# G74(a) — the Claude Code CLI as a Sleep engine

**Status:** approved 2026-09-01 (standing directive: G74 is the top blocker — "sleep is lowkey
bs… it has never run because I have no credits"). **Grounding:** the 2026-09-01 five-lens seam
map (`resolve_llm_fn`, every Sleep call site, the CLI's real flags, engine selection, the G74/G75
paper trail) plus **eight live verifications run against `claude` 2.1.252 on this machine** —
recorded in §9 with their raw numbers, because several contradict what the research assumed.

**One sentence:** implement the reserved `llm_mode="agent"` rung as `claude -p` subprocess calls
so the Sleep cycle runs on the user's already-connected Max plan with zero API credits, and make
every failure it can produce visible instead of silent.

---

## 1. What is actually broken (verified, and narrower than assumed)

- The active bank has **3** unprocessed episodes, not a backlog pile-up. The 2026-07-14 librarian
  run drained 988. Nothing regressed on 2026-06-18 — that day's commits were a *fix*; the engine
  simply ran out of OpenRouter credit afterwards. **The cost of the dead engine is 2.5 months of
  unconsolidated capture and a telemetry ledger holding exactly one line**, not an emergency.
- **The abort is upside-down.** With a non-empty queue and no engine, `sleep_cycle.py:261` returns
  *before* `_warm_logos_safely` (:474) and `_poll_connectors_safely` (:501), and
  `_refresh_questions_safely` only runs in the zero-episode idle branch (:231). So **capturing
  more episodes makes Sleep do strictly less work.** This is independent of which engine ships and
  is fixed here regardless.
- The user-visible string is a lie on a Max plan: *"check model id / API credits"*
  (`sleep_cycle.py:254-257`, red banner at `SleepView.swift:60`).

## 2. The seam contract the rung must satisfy

`resolve_llm_fn(settings, *, model, completion, stage, sink, bank) -> _call(*, messages,
response_format=None, **kw)` (`providers.py:135-142`, `:211`). Non-negotiables:

1. **Dual access.** Seven call sites read `resp.choices[0].message.content`; two
   (`dedup_sweep.py:120`, `source_rewrite.py:57`) read `resp["choices"][0]["message"]["content"]`.
   Ship a recursive dual-access mapping (`class _D(dict): __getattr__ = dict.__getitem__`).
   A `SimpleNamespace` or a bare dict each break one side.
2. **Sync/async duality.** The seam branches on `inspect.isawaitable` (`providers.py:225`); in
   agent mode the injected `completion` is never called, so that signal is gone. **Verified:**
   `inspect.iscoroutinefunction(litellm.acompletion) is True` and `…(litellm.completion) is False`,
   so inferring from the caller's `completion` is sound. Add an explicit `is_async: bool | None`
   override anyway.
3. **Accept-and-drop unknown kwargs**, except `timeout`, which is the only wall-clock guard Stage 1
   has (`entity_extractor.py:138`). Never forward `extra_body`/`temperature`/`max_tokens` to argv.
4. **`usage` stays optional** — `telemetry.usage_from_response` tolerates absence (`telemetry.py:174-208`).

## 3. The invocation (every flag verified present and accepted together)

```
claude -p --output-format json --safe-mode --strict-mcp-config --tools ""
        --no-session-persistence --model <alias|id> --system-prompt <TEXT>
        [--json-schema <SCHEMA>]
```
prompt on **stdin**, `cwd` = a scratch dir under `$CICADA_HOME` (never a bank, never the repo),
`env = scrubbed_env()`.

- `--safe-mode` disables CLAUDE.md, skills, plugins, hooks and **MCP servers** while leaving auth
  and model selection working — this is the recursion kill-switch. `--strict-mcp-config` with no
  `--mcp-config` is the independent second lock. Together they guarantee the spawned engine cannot
  call Cicada's own MCP tools and write its consolidation turns back into the bank.
- `--no-session-persistence` keeps engine turns out of `~/.claude/projects`, so G48 conversation
  identity never sees phantom sessions.
- **Never `--bare`** — it forces `ANTHROPIC_API_KEY`/`apiKeyHelper` and never reads OAuth, i.e. it
  is exactly the wrong mode for a subscription. `scripts/doctor.sh` gains a check for the announced
  flip of `-p` to bare-by-default, which would silently break this rung.

### 3.1 Structured output — the finding that changes Stages 2/3/4

**`--json-schema` works** (verified): the envelope gains a **`structured_output`** key holding the
*parsed object*, alongside `result` holding its string form. Six call sites pass
`response_format={"type":"json_object"}`; the rung translates that to `--json-schema` with a
per-site schema. This is strictly better than the prompt-level "reply with JSON only" workaround
the research assumed was the only option.

Belt and braces regardless: promote `entity_extractor._parse_json_lenient` (`:159-207`) to a shared
module and route all seven JSON sites through it. **`skill_extractor.py:89`,
`conflict_resolver.py:729` and `entity_resolver.py:706` call bare `json.loads` today** — a single
preambled answer makes Stage 4 return `[]`, Stage 3 skip, and Stage 2 answer "unsure", which
*creates a clarification and splits the entity*. That fragility predates this engine and ships as
its own task.

### 3.2 Response shim

```
{"choices":[{"message":{"role":"assistant","content": envelope["result"]},
             "finish_reason": envelope["stop_reason"]}],
 "model": <the priced model actually used>,
 "usage": {"prompt_tokens": input + cache_read + cache_creation,
           "completion_tokens": output,
           "prompt_tokens_details": {"cached_tokens": cache_read}}}
```
`usage_from_response` treats `prompt_tokens` as the **gross** prompt with cache counters as a
breakdown of it — fold, never add twice. **Verified necessary:** a 58 KB prompt reported
`input_tokens: 2` with `cache_creation_input_tokens: 19631`; reading `input_tokens` alone would
have recorded a 14k-token prompt as 2 tokens.

`modelUsage` is **multi-model** — a single call reported both `claude-haiku-4-5` (an internal
side-call) and the requested `claude-sonnet-5`. Never assume one key: record the model whose
`canonicalModel` matches the requested one, and sum cost across all of them.

## 4. Prompt-cache affinity (new; changes the cost model)

**Verified:** prompt caching persists **across separate `-p` processes**. A repeated 58 KB prompt
read 19,631 cached tokens and cost fell from $0.0917 to $0.0171 — **5.4×** — with a 1-hour
ephemeral TTL. A small (781-token) prompt cached nothing, i.e. there is a minimum size.

Consequence, and it is a design rule rather than an optimization: **every prompt the rung builds
puts stable content first and varying content last** — system text, then the shared corpus (the
entity context, the episode being consolidated), then the per-call question. A Sleep cycle makes
~200-350 calls that heavily reuse the same episode and entity text; prefix-ordered prompts make
most of them cache-hot within the 1-hour window.

## 5. Failure taxonomy and what the user sees

Detection order from the envelope: `rc 127` → binary missing; `rc 124` → timeout; non-JSON stdout →
unavailable; `is_error == true` → branch on `terminal_reason` (`budget_exhausted` → exhausted;
`api_error` + 404 → model not found; `api_error` + rate-limit text → throttled; "Not logged in" →
unavailable). Types live in a new `api/services/engine_errors.py`.

- **Retries are currently unreachable for this rung**: `_EXTRACT_RETRYABLE`
  (`entity_extractor.py:152-156`) is litellm-exception-typed, so a CLI failure matches nothing and
  gets zero retries. Widen it, and add classification branches at `:371-379`.
- **Circuit breaker inside the rung.** Stage 1 fans out per-episode with no batch abort, so one
  throttle would be re-hit once per remaining episode. After the first `EngineThrottled`,
  subsequent calls fail fast without spawning and the cycle stops cleanly with a distinct message
  ("Claude plan throttled — stopped cleanly, N episodes left queued"), leaving `processed: false`
  to do the rest.
- **Emit `kind="throttle"`.** `telemetry.KINDS` already lists it and `consumption_stats.py:249`
  already counts `throttle_events` — **nothing has ever written one.** This rung is the first.
- **`_llm_judge_same_entity`'s blanket `except → "unsure"`** (`entity_resolver.py:707-709`) turns
  engine failures into clarifications and split entity pages: the inbox floods and the graph
  fragments while the cycle reports success. Distinguish engine failure from model uncertainty and
  requeue on the former — **before** the rung goes live.

## 6. Telemetry: honest numbers for a subscription call

Three values are computed once, outside `_call`, and must become branch-dependent: `engine`
(hardcoded `"litellm"`, `providers.py:201`), `connection`/`billing` (`connection_for_model` maps
any model containing "claude" to `("byok-anthropic", "usage")`, `telemetry.py:211-221` — left alone
**every plan call is attributed to the disconnected BYOK API-key card and billed as real money**),
and `cost`.

An agent-mode event records `engine="claude-cli"`, `connection="claude-plan"` (must equal the
adapter id — `consumption_stats.per_connection` joins strictly on it), `billing="subscription"`,
`model` = the model the CLI actually used, `cost_usd=None`, and the envelope's `total_cost_usd` in
a separate **`equiv_cost_usd`** field. The envelope's `costBasis: "list"` says that figure is
list-price metering, not money charged — the dashboard shows it as "included in plan (≈ $X list)",
never as spend. The UI already prints `n/a` for null costs, so this degrades correctly today.

## 7. Latency, and the honest scope line

Measured on the live banks: Stage 1 fans out over episodes (`MAX_CONCURRENCY=10`) but chunks within
an episode are sequential; **Stage 2 is fully sequential and dominates** (mean 7.0 candidates per
name, p99 84, max 132 on the 1,731-entity bank). A 20-episode cycle is **~200-350 calls, ~90%
serialized** — 17-29 min at 5 s/call, up to ~3 h at 30 s/call. Survivable because
`POST /sleep/trigger` runs under `BackgroundTasks` and the queue is resumable; **not** survivable
at `mcp/server.py:606`, where a 60 s `/ask` timeout falls through to running `ask_service` in the
MCP process with no timeout at all.

**Therefore:** ship the naive per-call rung first with prefix-ordered prompts (§4), measure with
real telemetry, and treat Stage-2 batching (one judge call per name, plus a candidate cap — removes
~200 of ~300 calls) as the first follow-up, not a prerequisite.

**Trigger scope:** **user-triggered only in this slice** (`POST /sleep/trigger`, a human pressing
Run). Whether an unattended nightly cron counts as "ordinary, individual usage" is flagged
unadjudicated in the project's own compliance research; the scheduler stays on the existing engine
selection and is a separate decision.

**Out of scope:** G74(b) (the in-session agent that writes through MCP — proven already, coordinated
purely by the shared `processed:false` flag, needing no lock or handshake with this rung), G75, and
Stage-2 batching.

## 8. Configuration and UI

`llm_mode` gains `"agent"` (implemented) and `"auto"` (resolve to the agent rung when the Claude CLI
probe reports connected, else the configured provider, else none). The Claude connection card gains
a "Use for Sleep" affordance and honest copy: what it costs (plan quota, not money), that it is
user-triggered, and what happens on throttle. When the CLI is missing or logged out, the Sleep page
says exactly that with the fix, instead of "check API credits".

`scripts/doctor.sh` gains: engine resolves to something real; `claude -p` still OAuth (not `--bare`)
by default; no `ANTHROPIC_API_KEY` in the environment that would silently divert billing to an API
key (a documented upstream trap).

## 9. Verifications (run 2026-09-01 against `claude` 2.1.252 — raw results)

| # | Question | Result |
|---|---|---|
| V1 | Does the pinned flag set work at all, and what is the envelope? | **Yes**, rc 0. Keys: `type, subtype, is_error, result, structured_output, stop_reason, terminal_reason, session_id, num_turns, usage, modelUsage, total_cost_usd, duration_ms, api_error_status, permission_denials, uuid, …` |
| V1b | Does `--json-schema` constrain output? | **Yes** — `structured_output: {"ok": true}` parsed, `result` its string form |
| V1c | Is cost/usage populated under subscription auth? | **Yes**, `total_cost_usd: 0.00304`, `costBasis: "list"` (metering, not spend) |
| V1d | One model per call? | **No** — `modelUsage` held `claude-haiku-4-5` *and* `claude-sonnet-5` |
| V2 | Does a 58 KB prompt survive on stdin? | **Yes**, rc 0, correct answer, 1.6 s |
| V2b | Where do big-prompt tokens land? | `input_tokens: 2`, `cache_creation_input_tokens: 19631` — read `input` alone and you under-count ~10,000× |
| V5 | Prompt cache across processes? | **Yes** — repeat of the 58 KB call: `cache_read: 19631`, cost $0.0917 → **$0.0171**. (A 781-token prompt cached nothing — minimum size.) |
| V6 | Is `litellm.acompletion` detectably async? | **Yes** (`True`); `completion` is `False` |
| V8 | Is `ModelResponse` subscriptable? | Yes — moot, the shim covers both access styles |

**Still unverified, and honest about it:** the exact shape of a real 429/quota envelope (cannot be
produced on demand — log the full envelope on every failure and tighten once one is captured); and
whether `total_cost_usd` reflects quota actually consumed (`costBasis: "list"` suggests not, which
is why it is `equiv_cost_usd`).

## 10. Testing

Zero subprocess spawns in unit tests: an injectable runner replays recorded envelope fixtures
(success, structured-output, `budget_exhausted`, `api_error` 404, not-logged-in, rc 124, rc 127,
non-JSON stdout). Seam tests assert both attribute and subscript access on the shim, both awaited
and non-awaited call sites, and the emitted `UsageEvent` fields (engine/connection/billing/model/
`equiv_cost_usd`). A fake runner that throttles on call N asserts the cycle stops cleanly, the queue
stays intact, exactly one throttle event is recorded, and **no clarifications were minted**. One
end-to-end run against a throwaway bank with a fake runner asserts commit trailers name the real
model and the ledger's `by_stage` contains no `"unknown"`. The live pass (one real cycle on a copy
of the bank) is the controller's, not the suite's.
