# Provider Connections + Consumption Dashboard — Design

**Date:** 2026-08-28 · **Status:** design, awaiting Rodrigo's review · **Branch:** `dev`
**Backlog:** G50 (connections), G51 (dashboard), G52 (in-app ask-anything, captured only)
**Builds on:** [`../../goals/subscription-first-portability.md`](../../goals/subscription-first-portability.md) (G49 — the Session-Native Engine Ladder)
**Plans:** [`../plans/2026-08-28-provider-connections.md`](../plans/2026-08-28-provider-connections.md) · [`../plans/2026-08-28-consumption-dashboard.md`](../plans/2026-08-28-consumption-dashboard.md)

> Written without a live Q&A round. Every judgment call is listed under **Assumptions** — override any of them and the plans adjust.

---

## 1. Goal

Two user-facing capabilities that make Cicada usable — and honest about cost — for someone who pays for AI through subscriptions rather than API keys:

1. **Provider connections.** "Connect" a Claude plan, a ChatGPT plan, and (later) other agent subscriptions the same way; also connect usage-based API keys and a local Ollama. Show the current plan, allow disconnect, show the price.
2. **Consumption / traceability dashboard.** A minimal and an advanced view of what Cicada consumed: which connection/engine/model did what memory work, when, how much (invocations, tokens), and at what price — a GitHub-style activity calendar plus a Claude-Code-`/stats`-style statistics view. Subscription connections show the flat subscription price (and an *equivalent API cost* estimate); usage-based connections show a real per-model price breakdown.

Out of scope here (captured as **G52**): an in-app "ask your memory anything" surface over the existing `POST /ask`.

## 2. The compliance constraint that shapes everything

Research (2026-08-28, primary sources) settled how a third-party local app may "connect" a subscription:

| Provider | Compliant pattern | Forbidden / risky |
|---|---|---|
| **Claude (Pro/Max)** | Delegate to the **unmodified `claude` binary**: `claude auth status --json` → `{loggedIn, email, orgName, subscriptionType}`; `claude auth login` / `claude auth logout`; inference only via `claude -p --output-format json` (never `--bare`, which ignores OAuth). | Anthropic's compliance page: third parties may not offer claude.ai login, route requests through plan credentials, or "collect, store, or intermediate Claude.ai credentials or session tokens." Enforced since Feb 2026. So: **never read the Keychain blob, never call `api.anthropic.com/api/oauth/usage`.** |
| **ChatGPT (Plus/Pro)** | Delegate to **`codex`**: `codex login status` (exit 0 = logged in), `codex login --device-auth` (prints a code + URL — headless-friendly), `codex logout`; plan + email decoded **display-only** from the `id_token` JWT in `~/.codex/auth.json` (claim `https://api.openai.com/auth.chatgpt_plan_type`); inference via `codex exec --json`. | Running your own OAuth with the Codex client id (what Cline/OpenCode do) is tolerated and publicly endorsed by OpenAI leadership but undocumented — keep it out of v1, behind the adapter seam. Never call `chatgpt.com/backend-api/wham/usage`. |
| **Gemini / Copilot / others** | Same delegate-to-CLI shape (`gemini` Google sign-in, `copilot` GitHub device flow). Not in v1; the adapter protocol is designed so each is one file. | — |

Consequences: Cicada **owns no vendor token, ever**. A "connection" is a *probe* of a CLI's login state plus user preferences. Disconnect = run the CLI's logout. Live rate-limit windows for Claude have **no compliant source** (Cicada shows the throttle events its own runner observed instead); for Codex they are readable offline from the newest `token_count` event in `~/.codex/sessions/**` (advanced view only).

## 3. Assumptions (override any)

1. **Delegate-to-CLI only** for subscriptions (no in-app OAuth), per §2. "OpenAI OAuth connection" therefore means *sign in with your ChatGPT account through Codex*.
2. **Claude tier (Max 5x vs 20x) is user-selected**, not read from the Keychain (`claude auth status --json` only exposes `pro`/`max`). Price shows a range until the user picks.
3. **Connection state is machine-global** (`~/.cicada/`), not per memory bank — subscriptions belong to the person, banks to the memory. Ledger events carry a `bank` field.
4. **BYOK keys live in `~/.cicada/secrets.env` (0600)**, written by the backend, hot-loaded into `os.environ` (litellm reads keys from the environment, so no restart is needed). They are never written into `api/.env`, the memory repo, or git.
5. **Bearer-token auth on `localhost:8000` is a prerequisite** (G49's launch blocker). It is Task 1 of the connections plan because a key-writing endpoint without it is unacceptable. `GET /healthz` stays auth-free.
6. **Consumption is measured honestly per billing kind**: subscription rungs in *invocations + tokens where the CLI reports them* (Claude `-p --output-format json` returns `modelUsage` + `total_cost_usd` list-price estimate; Codex `exec --json` reports token counts) and labelled "included in plan — equivalent API cost ≈ $X"; usage-based rungs in real dollars via litellm `response_cost`; local = $0. Never invented token budgets (G49's refuted claim).
7. **The dashboard reads two sources**: Cicada's own telemetry ledger (new) and the memory repo's git log (existing `Cicada-Author` trailers), so the calendar shows history from before the ledger existed.
8. **Reading `~/.claude/stats-cache.json`** (Claude Code's own pre-aggregated `/stats` store: daily activity, per-model tokens, hour histogram) is allowed as an *optional advanced panel* labelled "Claude Code activity (whole machine)". It is not a credential and involves no network. Same for Codex session logs. Both parsers are tolerant and failure is non-fatal.
9. **Swift Charts** (macOS 14, already the deployment target) is used for bar/line charts; the calendar heatmap is a hand-built grid (Charts has no heatmap primitive worth fighting).
10. **A Swift test target is added** (`CicadaAppTests`) for pure logic only (bucketing, streaks, decoding). Views stay build-verified, not unit-tested — same as today.

## 4. Architecture overview

```
app (SwiftUI)                         api (FastAPI, localhost:8000, bearer token)
┌──────────────────┐   GET/POST       ┌──────────────────────────────────────────┐
│ ConnectionsView  │◀───────────────▶ │ routers/connections.py                    │
│  cards: state,   │                  │   services/connections/                    │
│  plan, price,    │                  │     base.py      Adapter protocol + models │
│  connect/disc.   │                  │     claude_cli.py  `claude auth …`          │
│  BYOK SecureField│                  │     codex_cli.py   `codex login …` + JWT    │
└──────────────────┘                  │     byok.py        secrets.env keys         │
                                      │     ollama.py      /api/tags probe          │
┌──────────────────┐                  │     registry.py    prefs + live status cache│
│ UsageView        │◀───────────────▶ │     secrets.py     ~/.cicada/secrets.env    │
│  minimal/advanced│                  │   services/pricing.py  subs table + litellm │
│  heatmap, tiles, │                  │ routers/consumption.py                     │
│  charts, tables  │                  │   services/telemetry.py   ledger writer     │
└──────────────────┘                  │   services/consumption_stats.py aggregates │
                                      │   services/harness_stats.py  stats-cache   │
                                      └──────────────────────────────────────────┘
                                                 ▲ record()            ▲ git log
        capture points ──────────────────────────┘                     │
        providers.resolve_llm_fn (usage+cost per call, stage-tagged)   │
        sleep_cycle._finalize (run summary)                            │
        mcp handle_write_claim (agentic write)                         │
        engines/* (G49 P1: claude -p / codex exec parsed usage)        │
                                                                        │
        ~/.cicada/telemetry/events-YYYY-MM.jsonl   <memory>/.git ──────┘
```

## 5. Subsystem A — Provider connections (G50)

### 5.1 Data model (`api/models/schemas.py`)

```python
class ConnectionKind(str, Enum):  subscription | usage | local
class ConnectionStatus(CamelModel):
    id: str                     # "claude-plan" | "chatgpt-plan" | "byok-openai" | "byok-anthropic" | "byok-openrouter" | "byok-gemini" | "ollama-local"
    label: str                  # "Claude plan"
    kind: ConnectionKind
    available: bool             # CLI installed / adapter usable on this machine
    connected: bool
    plan: str | None            # "max", "pro", "plus" … (raw vendor value)
    plan_label: str | None      # "Claude Max 20x"
    tier: str | None            # user-selected tier override ("5x"/"20x") for Claude Max
    account: str | None         # email (display only)
    price_usd_month: float | None        # flat subscription price (None for usage/local)
    price_note: str | None      # "verified 2026-08-28"; or the range note before tier is chosen
    billing: str                # "subscription" | "usage" | "free"
    engine_role: str | None     # which ladder rung this connection powers ("subscription-cli", "byok", "local")
    detail: str | None          # human hint: "Run `claude` once to sign in", version, errors
    login: LoginHint | None     # how to connect: {mode: "terminal"|"device-code"|"key", command: str|None}
```

### 5.2 Adapter protocol (`api/services/connections/base.py`)

```python
class ConnectionAdapter(Protocol):
    id: str; label: str; kind: ConnectionKind
    def available(self) -> bool
    async def status(self) -> ConnectionStatus          # live probe, never cached by the adapter
    async def begin_login(self) -> LoginSession          # terminal command | device-code stream | key-required
    async def logout(self) -> None
    def price(self, status) -> tuple[float | None, str | None]
```

All subprocess calls go through one helper `run_cli(argv, timeout=15, env=scrubbed)` that strips `ANTHROPIC_API_KEY`/`OPENAI_API_KEY` from the child env (so `claude` reports the OAuth state, not an API-key override) and never inherits Cicada's secrets.

- **`claude_cli.py`**: `available()` = `shutil.which("claude")`. `status()` = parse `claude auth status --json`. `begin_login()` returns `{mode:"terminal", command:"claude auth login"}` — the **app** opens Terminal with it (browser OAuth is interactive), then polls status. `logout()` = `claude auth logout`. Tier from registry prefs.
- **`codex_cli.py`**: `status()` = `codex login status` exit code + JWT decode of `~/.codex/auth.json` (`base64url` payload only; no signature check; no token leaves the process; fields: `chatgpt_plan_type`, `email`). `begin_login()` spawns `codex login --device-auth`, captures the one-time code + URL from stdout into a `LoginSession{mode:"device-code", code, url, session_id}` the app displays; a background task waits for the process and flips status. `logout()` = `codex logout`.
- **`byok.py`**: one adapter instance per provider (`openai`, `anthropic`, `openrouter`, `gemini`), keyed to the env var name. `status().connected` = key present in `os.environ` (loaded from `secrets.env` or the shell). `begin_login()` → `{mode:"key"}`; the key itself arrives via `PUT /connections/{id}/key`. `logout()` removes the key from `secrets.env` + `os.environ`. Optional live validation on save (`litellm` 1-token call) — off by default, on with `?validate=true`.
- **`ollama.py`**: `available()` = GET `{ollama_base_url}/api/tags` reachable; `connected` = configured `ollama_model` present in tags. No login; "connect" = instruction to `ollama pull`.

### 5.3 Registry, prefs, secrets

- `~/.cicada/connections.json` (0600): `{ "claude-plan": {"tier": "20x"}, "byok-openai": {"enabled": true}, "order": [...] }` — preferences only. **No plan snapshots, no tokens, no emails on disk.**
- `~/.cicada/secrets.env` (0600, `KEY=value` lines): written by `secrets.py` atomically; loaded into `os.environ` at backend startup **and** after every write (`load_secrets(override=False)` — shell exports win, matching the existing `.env` precedence).
- `registry.py`: `list_adapters()`, `get(id)`, in-memory status cache with 30 s TTL (live probes shell out; the app polls every 30 s already), invalidated on login/logout/key writes.
- `CICADA_HOME` env var overrides `~/.cicada` (tests use `tmp_path`).

### 5.4 API (`api/routers/connections.py`)

```
GET    /connections                       → [ConnectionStatus]
GET    /connections/{id}                  → ConnectionStatus (live, bypasses cache with ?fresh=true)
POST   /connections/{id}/login            → LoginSession {mode, command?, code?, url?, sessionId?}
GET    /connections/{id}/login/{sid}      → {state: pending|done|failed, detail}
POST   /connections/{id}/logout           → ConnectionStatus
PUT    /connections/{id}/key  {key}       → ConnectionStatus   (BYOK only; ?validate=true)
DELETE /connections/{id}/key              → ConnectionStatus
PUT    /connections/{id}/prefs {tier?, enabled?} → ConnectionStatus
```

All under the bearer-token dependency. `GET /status` gains `connections: {connected: [ids], engine: str|None}` so the menu bar can show "running on Claude Max".

### 5.5 Auth prerequisite (G49 P0, Task 1)

`api/services/auth.py`: token file `~/.cicada/api_token` (0600, generated on first start), FastAPI dependency `require_token` applied app-wide via a router-level dependency list except `/healthz`. `CICADA_API_TOKEN` env overrides. `APIClient.swift` reads the same file (`FileManager` in the sandbox-free app) and sends `Authorization: Bearer …`; MCP `mcp/server.py` does the same when it proxies to the backend. `install.sh`/`doctor.sh` learn the file. Keep the diff minimal: one dependency, one header.

### 5.6 App — Connections page

- New `AppTab.connections` ("Connections", icon `person.crop.circle.badge.checkmark`) in the **Setup** section, above `connect` (which stays as the "Agent setup" MCP catalog; its onboarding sheet later becomes the G49 plan-picker wizard).
- `ConnectionsViewModel` (`@Observable`): `connections`, `load()`, `beginLogin(id)`, `logout(id)`, `saveKey(id, key)`, `removeKey(id)`, `setTier(id, tier)`; 30 s refresh while visible; device-code polling every 2 s while a login session is pending.
- `ConnectionsView`: one `glassCard()` per connection: logo (reuse `Resources/logos/`), name, status pill (Connected / Not connected / Not installed), plan badge + price line ("Claude Max 20x · $200/mo" / "OpenAI API · usage-based" / "Ollama · free, local"), account email, primary button (**Connect** → Terminal hand-off with the command shown in a `CommandBox`, or device-code sheet with the code + "Open URL" button, or a `SecureField` + Save for BYOK; **Disconnect** when connected — confirm sheet warning that `claude auth logout` also resets Claude Code's onboarding), tier picker for Claude Max.
- Terminal hand-off: `NSWorkspace` + AppleScript `tell application "Terminal" to do script "claude auth login"`; fallback copies the command.

## 6. Subsystem B — Consumption / traceability dashboard (G51)

### 6.1 Ledger (`api/services/telemetry.py`)

Append-only JSONL, one file per month: `~/.cicada/telemetry/events-YYYY-MM.jsonl`. Never inside the memory repo, never in git. One event per LLM call or per unit of memory work:

```json
{"ts":"2026-08-28T03:12:44.120Z","kind":"llm_call","stage":"extraction",
 "connection":"byok-openai","engine":"litellm","model":"gpt-5.4-mini","bank":"claude-chats",
 "invocations":1,"input_tokens":5120,"output_tokens":410,"cache_read_tokens":0,"cache_write_tokens":0,
 "cost_usd":0.0031,"equiv_cost_usd":0.0031,"billing":"usage","duration_ms":1830,
 "refs":{"cycle_id":"sleep_2026-08-28_031200","episode_ids":["ep_2026-08-27_004"],"commit":null,"session_ref":null},
 "throttled":false,"ok":true}
```

`kind ∈ {llm_call, sleep_run, agentic_write, ask, import, throttle}`; `stage ∈ {extraction, disambiguation, synthesis, contradiction, skills, enrichment, ask, dedup, driver, structural}`; `billing ∈ {subscription, usage, free}`. `cost_usd` is null for subscription/free; `equiv_cost_usd` is always the list-price estimate when tokens are known (litellm `cost_per_token`, falls back to null for unknown models). `record(event)` is synchronous, non-blocking on failure (log + drop), and appends via a single `os.write` per line.

### 6.2 Capture points

1. **`providers.resolve_llm_fn`** gains `stage: str | None` and `telemetry: TelemetrySink | None` kwargs. The returned `_call` wraps the completion (sync or awaitable — detect with `inspect.isawaitable`), reads `response.usage` (dict or object; `prompt_tokens`/`completion_tokens`/`prompt_tokens_details.cached_tokens`), `response._hidden_params.get("response_cost")`, times the call, and records one `llm_call`. Existing behaviour is byte-identical when `telemetry` is None (the default is the module-level sink, disabled under tests via `CICADA_TELEMETRY=off`).
2. **The four direct-litellm callsites** (`entity_extractor.py:234`, `entity_resolver.py:690`, `link_enrichment.py:252`, `ask_service.py:260`) are rerouted through `resolve_llm_fn(..., stage=…)`. This is G49 P4's "seam completion", pulled forward because the dashboard is blind without it. `test_llm_seam_adoption.py` extends to all seven.
3. **`sleep_cycle._finalize`** records one `sleep_run` event: cycle id, engine, model(s), episodes processed/requeued, entities created/updated, duration, commit sha (from `commit_changes` return — extended to return the hash).
4. **`mcp/server.py::handle_write_claim`** records an `agentic_write` event (`connection:"session"`, `engine:"mcp-client"`, model unknown, `invocations:1`, refs: entity/claim ids, `session_ref` when G48 lands). Token-free by nature — counted as memory work, not cost.
5. **Engines (G49 P1, when built)** call the same `record()`: `claude_cli` parses `-p --output-format json` (`modelUsage`, `total_cost_usd` → `equiv_cost_usd`, `session_id`), `codex_cli` sums `token_count` events from `exec --json`. `EngineThrottled` records a `throttle` event.

### 6.3 Aggregation (`api/services/consumption_stats.py`) and API (`api/routers/consumption.py`)

```
GET /consumption/summary?range=30d|month|all      → totals for the tiles
GET /consumption/calendar?weeks=53                → [{date, memory_writes, events, tokens, cost_usd, equiv_cost_usd, level:0-4}]
GET /consumption/stats?range=…                    → advanced breakdowns
GET /consumption/connections?range=…              → per-connection cost cards
GET /consumption/harness                          → optional Claude Code stats-cache + Codex rate-limit snapshot (advanced)
```

- **summary**: `{cost_usd, equiv_cost_usd, subscription_usd_month, invocations, tokens, memory_writes, sleep_runs, agentic_writes, streak_current, streak_best, range}`.
- **calendar**: merges ledger days with `git log --format=%ad --date=short` day counts of `Cicada-Author`-trailered commits (memory writes). `level` = quantile bucket 0–4 over the non-zero days (GitHub semantics). Weeks start Monday; always 53 columns ending today.
- **stats**: `by_model[]` (tokens in/out/cache, invocations, cost, equiv_cost), `by_stage[]`, `by_connection[]`, `by_bank[]`, `hour_histogram[24]`, `peak_day`, `longest_sleep_run`, `favorite_model`, `lifetime_tokens`, `first_event`, plus `series[]` (daily tokens+cost for the charts).
- **connections**: per connection `{id, label, billing, price_usd_month, cost_usd, equiv_cost_usd, invocations, tokens, by_model[]}` — subscription → `price_usd_month` + equiv; usage → real `cost_usd` with per-model rows; local → free.
- **harness** (`harness_stats.py`): tolerant reader of `~/.claude/stats-cache.json` (`dailyActivity`, `modelUsage`, `hourCounts`, `totalSessions`, `longestSession`) and of the newest `token_count.rate_limits` in `~/.codex/sessions/**` (`primary/secondary.used_percent`, `resets_at`, `plan_type`). Any failure → `null` fields, HTTP 200.

Streaks: consecutive days (ending today or yesterday) with `memory_writes + events > 0`.

### 6.4 Pricing (`api/services/pricing.py`)

- `SUBSCRIPTION_PRICES` (USD/month, `verified: 2026-08-28`): `claude-plan`: pro 20, max-5x 100, max-20x 200; `chatgpt-plan`: go 8, plus 20, pro-5x 100, pro-20x 200; `gemini`: pro 19.99, ultra-5x 99.99, ultra-20x 199.99; `copilot`: pro 10, pro-plus 39, max 100. `price_for(connection_id, plan, tier) -> (usd | None, note)`. Unknown plan → `(None, "price unknown for '<plan>'")`.
- Usage: `estimate_cost(model, in, out, cache_read, cache_write) -> float | None` via `litellm.cost_per_token` with the model id normalised (`openrouter/` prefix stripped for lookup). Offline: litellm bundles its price table; no network.

### 6.5 App — Usage page

- New `AppTab.usage` ("Usage", icon `chart.bar.xaxis`) in the **Provenance** section next to Contributors.
- `UsageViewModel`: `mode: .minimal|.advanced` (persisted `@AppStorage("cicada.usageMode")`), `range`, `summary`, `calendar`, `stats`, `connections`, `harness`; `load()` fans out the five requests; refresh on appear and after a Sleep run finishes.
- **Minimal view** (default): four stat tiles — *This month* (real $ if any usage-based spend; else "Included in plan · ≈ $X API-equivalent"), *Memory writes*, *Sleep runs*, *Streak* — then the **calendar heatmap** (53×7 grid, 5-level ramp, hover tooltip "Aug 12 · 3 memory writes · 41k tokens", click → filters the advanced tables to that day), then a one-line "Connections: Claude Max 20x · $200/mo, OpenAI API · $3.12 this month".
- **Advanced view** adds: per-connection cost cards (plan, price, real vs equivalent cost, live windows when available, throttle events); Swift Charts — daily tokens (stacked by model) and daily cost; tables — by model (in/out/cache/cost), by stage, by bank; `/stats`-style facts row — lifetime tokens, favorite model, peak day, longest sleep run, peak hours (24-bucket bar); optional "Claude Code activity (whole machine)" panel from `/consumption/harness` with a clear label that it is the harness's own data, not Cicada's.
- Theme: `CicadaTheme.heatRamp(level:)` — 5 steps derived from `accent` for both palettes; nothing else new.

### 6.6 Honesty rules (copy)

- Subscription rows never show a dollar figure as "spent". They show `$<price>/mo` and "≈ $X at API list price" with the note *estimate — not billed*.
- No rate-limit percentages for Claude (no compliant source). Show "throttled N times this week" from the ledger instead.
- Stats-cache and Codex session panels say where the data comes from.

## 7. Error handling

- Adapters never raise into routers: every probe returns a `ConnectionStatus` with `available=false`/`detail` on failure; CLI timeouts (15 s) → `detail: "claude did not respond"`.
- Ledger writes are fire-and-forget; a corrupt line is skipped on read (logged once per file).
- Missing `~/.cicada` is created lazily with 0700.
- App decoding stays tolerant (`try? … ?? default`) so an older backend doesn't blank the pages.

## 8. Testing

- Python: hermetic. Adapters take an injectable `runner(argv) -> (rc, stdout, stderr)`; JWT decode tested with a hand-built unsigned token; registry/secrets tested under `CICADA_HOME=tmp_path`; telemetry tested with the seam's `_FakeCompletion` (already returns `usage`); aggregation tested against a fixture ledger + a temp git repo with `Cicada-Author` commits (reuse `test_contributors.py` helpers); routers via `TestClient` with the token header.
- Swift: new `CicadaAppTests` target for `HeatmapBuckets`, `Streaks`, and model decoding; views compile-checked via `swift build`.

## 9. Sequencing and dependencies

1. Connections plan Task 1 (bearer token) → everything else.
2. Connections adapters + API + page (Tasks 2–9).
3. Dashboard: ledger + seam capture + seam completion (Tasks 1–4) can proceed in parallel with connections Tasks 3+; the connections cost cards need `pricing.py` + `GET /connections` (connections Task 5) — schedule dashboard Task 6 after that.
4. G49 P1 engines plug into `telemetry.record()` and `registry` when they land; nothing here blocks on them.

## 10. Open questions for Rodrigo

- Tier override vs reading Keychain for Claude Max 5x/20x — assumed override (compliance-safe). OK?
- Should the Usage page also import *external* harness cost (ccusage-style, parsing `~/.claude/projects/**/*.jsonl`)? Assumed no for v1 — the stats-cache panel covers the "/stats feel" without a JSONL parser.
- Gemini/Copilot adapters: ship as "coming soon" cards (greyed) or hide until built? Assumed hidden.
