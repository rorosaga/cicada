# Settings redesign — Track C: G122 engine picker + G126 Integrations page — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn Settings from a four-tab `TabView` into a five-section `NavigationSplitView` sidebar (General · Sleep · Integrations · Agents · Plans & keys), give Settings → Sleep a real engine-and-model picker backed by a new `GET/PUT /sleep/engine` endpoint (G122), and give Settings → Integrations a categorized, logo-first page over the existing channel registry (G126, page only — no new adapters).

**Architecture:** Backend adds one resolution rung to the existing engine ladder (`engine_select.resolve_llm_mode` reads a `sleep-engine` pseudo-connection pref when `CICADA_LLM_MODE` was never set) plus a new read/write surface over it (`GET/PUT /sleep/engine`, backed by a new `api/services/sleep_engine_prefs.py`). App adds a `SettingsSection` sidebar (replacing the `TabView`), an `EngineCard` view + thin `SleepEngineViewModel` for the Sleep section, an `IntegrationsView` + `IntegrationCategory` table for the Integrations section (reusing `ChannelActions` and `AddSourceTile`, and presenting `ConnectorSetupPanel` in a new `.popover` for a connector's connect/disconnect action — spec Track C's own words — since no existing view already composes the panel that way), and a tiny app-wide `AppRouter` so an Integrations row can hand off a one-shot import to the Feed's `+` sheet.

**Tech Stack:** Python 3 / FastAPI / Pydantic (`api/`), SwiftUI + XCTest (`app/CicadaApp`), markdown + git bank.

**Spec:** `docs/superpowers/specs/2026-09-05-study-desk-zoom-settings-sources-design.md` § Track C. Backlog rows **G122** (engine & model picker), **G126** (Integrations page — adapters explicitly out of scope). Rulings: TODO.md ruling 4 (scheduled cycles never spend plan quota — the picker DISPLAYS both previews rather than hiding the rule), the G124 no-prices/tokens ruling, portability (no owner name, no author-machine path), decode tolerance for every new Swift field, the font rule (`CicadaTheme.font(size:)` only — `FontLiteralLintTests`), `CopyConstantsTests` (no view retypes a cross-page pointer literal).

## What the code actually does today (verified against `dev` @ `2312887`)

- **Engine ladder** (`api/services/engine_select.py`, 210 lines): `resolve_llm_mode(settings, registry=None, *, user_triggered=True) -> (mode, why)`. Precedence: explicit `CICADA_LLM_MODE ∈ {agent, local}` wins with zero registry touch (verified live: `test_an_explicit_agent_mode_wins_without_probing` passes a registry whose `.prefs()` raises `AssertionError`, proving nothing is read) → a duck-typed `Settings` stand-in (no `model_copy`) bails to `byok` → **ruling 4**: `if not user_triggered: return "byok", "scheduled cycle — …"` → an unrecognized mode degrades to `byok` → `auto`/`byok` consult `registry.prefs()` for the Claude card's `use_for_sleep` toggle, then probe `claude-plan`, then (only for `auto`) `ollama-local`. `resolve_settings(...)` wraps this into a `Settings` copy: `settings.model_copy(update={"llm_mode": mode})` only when `mode != configured`, guarded by `hasattr(settings, "model_copy")` (fix round 1 M2 — several hermetic Sleep tests pass a `SimpleNamespace` predating `llm_mode`). `ENGINE_LABELS = {"agent": "claude-cli", "local": "ollama", "byok": "litellm"}`; `engine_label(settings)` reads `ENGINE_LABELS[llm_mode]`. `USE_FOR_SLEEP_PREF = "use_for_sleep"`, `CLAUDE_CONNECTION_ID = "claude-plan"`, `OLLAMA_CONNECTION_ID = "ollama-local"` are the module's existing pref-key constants (line 39-41).
- **`api/config.py`**: `llm_mode: str = "byok"` (line 107, env `CICADA_LLM_MODE`), `ollama_model: str = "llama3.1"` (110), `ollama_base_url` (112), `agent_model: str = "sonnet"` (119), `agent_disambiguation_model: str = "haiku"` (120), `litellm_model: str = "gpt-5.4-mini"` (71), `litellm_disambiguation_model: str = "gpt-5.4-nano"` (78). **VERIFIED**: `"llm_mode" in Settings().model_fields_set` is `False` for a default (no env) construction and `True` only when the env var is actually set — pydantic-settings marks env-sourced fields as set, same as an explicit constructor kwarg. This is the "explicit env" test the new rung must use.
- **Registry prefs** (`api/services/connections/registry.py`): `Registry.prefs() -> dict` reads `$CICADA_HOME/connections.json` (empty dict on any read error, line 44-48); `set_pref(connection_id, key, value)` (50-60) does read-merge-write, `chmod(0o600)`, then `self.invalidate()` — `value=None` **removes** the key rather than storing `null`. Nothing validates `connection_id` against `adapters()` inside `set_pref`/`prefs()` — a pseudo-connection id like `"sleep-engine"` that has no real adapter is a completely ordinary dict key here (only `Registry.get(connection_id)`, used by the `/connections/{id}` router, raises `KeyError` for an unknown id — this plan's new endpoints call `set_pref`/`prefs()` directly and never go through `Registry.get`). `Registry.statuses(fresh=False)` (152-176) probes every adapter concurrently, cached 30s, and is what `GET /connections` already uses — this plan reuses it rather than adding a second probe path. `_ollama_fetch_tags = ollama._http_tags` (line 32) is the **existing, test-patched** module-level hook (`test_connections_api.py`'s `client` fixture does `monkeypatch.setattr(registry, "_ollama_fetch_tags", no_tags)`) — the new service must call through this same hook, not `ollama._http_tags` directly, so the existing hermetic pattern keeps working unchanged.
- **`ollama.py`** (`OllamaAdapter`): `status()` sets `available` (server reachable) / `connected` (the *configured* `ollama_model` is actually pulled) / `detail` — it does **not** expose the full tag list on `ConnectionStatus` (that schema has no `models` field), so the new candidate list must fetch tags itself via the same `_ollama_fetch_tags` hook.
- **`agent_engine.py`**: `_MODEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:-]*$")` (line 241, private) is the exact charset `build_argv` enforces on `--model` before any subprocess spawns; `model_for_stage(settings, stage)` (332-336) returns `agent_disambiguation_model` for `stage == "disambiguation"` else `agent_model`, both `.strip() or DEFAULT_AGENT_MODEL`. No public wrapper around `_MODEL_ID_RE` exists yet — Task 1 adds one (`is_valid_model_id`) rather than reaching across modules at a private name.
- **`api/routers/sleep.py`** (188 lines): already mounted (`api/main.py:167`, `app.include_router(sleep.router, tags=["sleep"])`) with `/sleep/trigger`, `/sleep/cancel`, `/sleep/status`, `/sleep/history[/…]`, `/sleep/episodes`, `/sleep/schedule` (GET/PUT, lines 173-187). The schedule PUT pattern (`cfg: ScheduleConfig` body, `Settings = Depends(get_settings)`, direct call into a service module, no extra registry DI layer) is the template Task 1's new endpoints follow — no new router file needed.
- **`api/routers/connections.py`**: `PrefsBody(CamelModel)` (20-27) with `tier`/`enabled`/`use_for_sleep` all `Optional`, and the `"tier" in body.model_fields_set` idiom (line 106) to tell "omitted" from "explicitly null" — Task 1's `SleepEngineChoice` PUT body reuses this exact idiom for `model`/`disambiguationModel`.
- **`api/models/schemas.py`**: `CamelModel` (line 8-13, `alias_generator=to_camel, populate_by_name=True, serialize_by_alias=True`) is the base every wire schema in this plan extends. `ConnectionStatus` (1701-1727), `ConnectionKind`, `LoginHint` already model one connection card and are NOT reused for engine candidates (a candidate needs a `models: [str]` list and no login/billing fields — a new, smaller `SleepEngineCandidate` is cleaner than bolting fields onto `ConnectionStatus`). `ScheduleConfig` (1241-1259) is the sibling schema whose doc-comment style (cites the ruling by name) this plan's new schemas match.
- **`api/services/channel_registry.py`**: `CHANNEL_IDS = _NON_CONNECTOR_HEAD + tuple(ADAPTERS.keys()) + _NON_CONNECTOR_TAIL` (line 49) = 13 ids in this fixed order: `chat-export:claude, chat-export:chatgpt, chrome-bookmarks, safari-bookmarks, safari-tabs, notes, rss, calendar` + `pinterest, reddit, x` (`api/services/connectors/__init__.py::ADAPTERS`, line 69-73) + `telegram, files`. `build_channels(...)` (line 193) returns one dict per id via `_origin_channel`/`_sync_channel`/`_connector_channel`/`_subscription_channel`, each already carrying a server-composed `detail` string and `actions: [str]` (`"sync"|"poll"|"connect"|"disconnect"|"import"|"manage"`). **Nothing here changes in this plan** — Integrations reads the same `GET /sources/channels` response the Feed page already consumes.
- **Swift `SourceChannel`** (`Models/SourceChannel.swift`): `id, label, connected, count, lastSync, detail, lastError, actions` — every field but `id` optional-with-default (tolerant `init(from:)`, lines 33-43); `lastSyncDate` (47-59) parses three ISO shapes. **`Store.channels`** (`Sync/Store.swift:29`) and **`Store.sourcesOverview`** (`:35`) are the two domains Integrations reads — both already hydrated/kept live by the Store, no new fetch needed.
- **Swift `SourceOverview`** (`Models/SourceOverview.swift`): `SourceKind` enum includes `.harness` (line 6); a harness row carries `harness: String?` (line 30) — the "captured by the Stop hook / MCP" informational rows Task 4 adds are exactly the `kind == .harness` rows already present in this Store domain.
- **`ChannelActions`** (`Views/Sources/ChannelActions.swift`, 30 lines): `static func sync(_ channelId: String, store: Store) async throws -> String` and `static func poll(_ channelId: String) async throws -> String` — the two actions Track D's card/page already share; Task 4 reuses these verbatim, no new sync/poll path.
- **`ConnectorSetupPanel`** (`Views/Capture/Sheets/ConnectorSetupPanel.swift`): `ConnectorSetupPanel(connectorId:vendors:vendor:)`, `@Environment(Store.self)`, already renders credentials/OAuth-status/Sync now/Disconnect for `pinterest`/`reddit`/`x`. **VERIFIED there is no existing `.popover(ConnectorSetupPanel)` composition to copy** — the spec (Track C §3) asks for one, but it does not exist yet: `AddSourceSheet.swift:583` renders the panel inline as one `case` of its own multi-step sheet body (not a popover), and `ConnectedChannelsStrip.handle` (`Views/Feed/ConnectedChannelsStrip.swift:129-138`) routes its `"connect"`/`"disconnect"` actions through `default: onManage(AddSourceTile.forChannel(channel.id))` — opening that same full `AddSourceSheet`, never a popover of the panel alone. Task 4 is therefore building a genuinely new composition (per the spec's own direction — not copying a pattern that "already do[es] elsewhere", corrected in 4.4 below), which needs its own per-row `@State private var vendor: WalkthroughVendor` binding (the panel's `vendor` parameter is a `@Binding`, see `AddSourceSheet.swift:217`) since none of the three existing call sites hand one down from outside.
- **`ImportFamilies.swift`**: `enum AddSourceTile` (members include `.instagram, .youtube, .linkedin, .tiktok, .reddit, .pinterest, .x, .safari, .chrome, .chatExport, .rssFeed, .calendar, .telegram, .bookmarksFile, .pasteLink, .appleNotes`) and `AddSourceTile.forChannel(_:) -> AddSourceTile?` (`AddSourceSheet.swift:169`) already map a channel id onto its catalog tile.
- **`FeedView.swift`**: owns `@State private var showAddSheet = false` / `@State private var sheetTile: AddSourceTile?`, `.sheet(isPresented: $showAddSheet) { AddSourceSheet(initialTile: sheetTile) { showAddSheet = false } }` (lines 11-12, 94-95), and a private `openSheet(_ tile: AddSourceTile?)` (line 116) that stages the tile and flips the flag — Task 4's router hook calls into a new `consumePendingAddSource()` that calls this exact same `openSheet`.
- **`ContentView.swift`**: `enum AppTab` (`Views/Sidebar/SidebarView.swift:13-48`) — raw values ARE the literal display strings (`case graph = "Graph"`, …) and `restored(from:)` (23-32) maps any unrecognized/retired raw value to `.graph`. `ContentView.body` mounts `GraphContainerView` permanently (never torn down — G109) and switches every other tab in `otherTabContent` (145-174); `selectedTab` is `@State` + `@AppStorage("cicada.selectedTab")`.
- **`CicadaApp.swift`**: `@main struct CicadaApp: App` builds one `Store` plus every view model as a thin projection over it in `init()`, injects them into `WindowGroup` (`.environment(...)`, lines 83-92) and into `Settings { SettingsScene() .environment(connectionsVM).environment(sleepVM).environment(store) }` (lines 215-226) — the **same** `sleepVM`/`store` instances the main window uses, so a Sleep-section edit and the main window's Sleep page never drift.
- **`Copy.swift`**: `schedule = "Schedule"`, `settingsSchedule = "\(settings) → \(schedule)"`, `scheduleSubtitle = "When Sleep runs on its own, and what powers it."`, `changeInSettingsSchedule = "Change in \(settingsSchedule)"`, `engineLabel(_ id: String) -> String` (already maps `"claude-cli"/"ollama"/"litellm"` to human words — reused as-is by the new preview lines). Five call sites of the four `schedule*` constants outside their own definitions: `SettingsScene.swift:24-25` (tab item, replaced wholesale by Task 2), `SettingsSleepView.swift:39` (title/subtitle, replaced by Task 3), `HowSleepWorks.swift:66,69` (a pointer sentence), `StudyListCard.swift:224` (the study list's footer pointer). `CopyConstantsTests.swift:41` pairs `(Copy.schedule, Copy.scheduleSubtitle)` in its subtitle-shape test, and `testNoViewRetypesAPointerLiteral` (line 67) bans the literal `"Plans & keys"` (among others) anywhere outside `Copy.swift` — this is why a new `SettingsSection`/`IntegrationCategory` enum must never hardcode a Copy-owned display string as a raw value.
- **`FontLiteralLintTests.swift`**: greps every file under `Sources/CicadaApp` (except `Theme/CicadaTheme.swift`) for a literal `.system(size:` / `Font.system(size:` — every new view in this plan must route sizes through `CicadaTheme.font(size:weight:design:)`.

## Global Constraints

- Work ONLY in `/Users/rorosaga/Documents/roros_lab/cicada/.worktrees/settings` (branch `feat/settings-redesign`, based on `dev` @ `2312887`). Every shell command is `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/settings && <cmd>` with absolute paths (`zoxide` hijacks relative `cd`; ignore its stderr warning). Never an unquoted `grep --include=*.ext` (zsh globbing breaks it) — quote it or use `rg`.
- NEVER read `/Users/rorosaga/Documents/roros_lab/cicada/memory` (any bank), `~/.cicada`, `~/Library`, or `~/.claude/projects`. Test fixtures are synthetic (`alpha-project`, `bob-example`, `example.com`).
- Python: `api/.venv/bin/python -m pytest <files> -q -p no:cacheprovider`; the full suite `api/tests` must report **0 failures** (2014 passed on 2026-09-03). `test_agent_provenance.py::test_a_decay_only_change_lands_in_its_own_cicada_authored_commit` is order-dependent and pre-existing — if it's the ONLY red, re-run it alone and report both results.
- Swift: `cd .../app/CicadaApp && swift build 2>&1 | tail -5` must succeed and `swift test 2>&1 | tail -20` must report **0 failures** (SourceKit diagnostics naming other worktrees are noise).
- NEVER run `make dev`, `make install-app`, `swift run`, or launch/kill the Cicada app — the owner's installed app is live; the orchestrator installs at the end.
- Never `git add -A`; stage named files only. Never commit `memory/`, `logs/`, `.claude/`, `api/.venv`, or `*-report.md`. Do not push. Do not create branches/worktrees. Do not dispatch subagents. Ignore Devin/PR comments.
- **Secrets rail**: the engine prefs hold a **mode and a model name only, never a key** — `~/.cicada/secrets.env` is untouched by this plan.
- **Ruling 4 stays binding and VISIBLE**: a scheduled cycle never spends plan quota; the picker shows both `preview.manual` and `preview.scheduled` rather than hiding the asymmetry.
- **No prices, no token counts, anywhere in this plan's UI** (G124).
- **Font rule**: every new `.font(…)` call goes through `CicadaTheme.font(size:weight:design:)` — `FontLiteralLintTests` fails the suite on a literal.
- **Copy rule**: every cross-page pointer is a `Copy.*` constant, never a retyped literal — `CopyConstantsTests` greps for both banned literals and subtitle shape.
- **Decode tolerance**: every new Swift field on a network-decoded struct is optional-with-a-default via a tolerant `init(from:)`, so an older backend payload still decodes (tested).
- **Portability**: no owner name, no author-machine path, in shipped code or docs.
- Docstrings explain WHY, citing the G-row/ruling that motivated them; match the density of the files touched.
- Line numbers above are from `2312887` and drift as tasks land — read the cited code before editing it.

## Rulings (binding — decided here so the brief's open choices don't block implementation)

- **R1 — no new router file.** `GET/PUT /sleep/engine` land in the existing `api/routers/sleep.py` (already mounted), following the `/sleep/schedule` GET/PUT pattern verbatim. A separate `sleep_engine.py` router would split one page's backend across two files for no reader benefit.
- **R2 — prefs gate is `model_fields_set`, gated additionally by object shape.** The new engine_select rung reads `~/.cicada/connections.json`'s `sleep-engine` pref only when **both** (a) `hasattr(settings, "model_fields_set")` (a real pydantic `Settings`, never the `SimpleNamespace` stand-ins several hermetic Sleep tests pass) **and** (b) `"llm_mode" not in settings.model_fields_set` (the env var was never set). This keeps every existing duck-typed-Settings test byte-for-byte unaffected (zero new registry touch for that shape) while giving a real install's unconfigured default (`llm_mode` at its class default, no env) the new rung. This is a stricter gate than "no env var", but it is the one that provably can't regress `test_an_explicit_agent_mode_wins_without_probing`-style assertions.
- **R3 — a prefs-chosen "agent" is not a dotfile edit; ruling 4 still applies to it.** `resolve_llm_mode`'s ruling-4 early-return (`if not user_triggered: return "byok", …`) fires for a prefs-resolved `"agent"` exactly as it does for the `auto`/`byok` rungs — only an *explicit* `CICADA_LLM_MODE=agent` in `api/.env` may run the plan on the nightly schedule. A prefs-resolved `"local"` is never gated by trigger source at all (Ollama spends no plan quota, so there is nothing for ruling 4 to protect against).
- **R4 — the picker's model override is all-or-nothing with its mode.** When `CICADA_LLM_MODE` is explicit, `resolve_settings` applies **neither** a prefs mode **nor** a prefs model/disambiguation-model override — the dotfile is fully authoritative for both, so a UI-only model tweak can never silently ride along behind an operator's deliberate env pin. This also means `_model_overrides` is only ever consulted in the same branch that already reads `registry.prefs()` for the mode rung — no second, independent prefs read.
- **R5 — `codex` is a permanently-disabled row, never a settable mode.** `PUT /sleep/engine` validates `mode ∈ {auto, agent, byok, local}` (the four literal env values `CICADA_LLM_MODE` accepts) — `"codex"` is never accepted. **VERIFIED citation correction:** a `codex exec` engine rung is proposed in **G49** ("Session-Native Engine Ladder" — `claude -p`/`codex exec` → local Ollama → BYOK), still `🔲` open; `engine_select.py` today has no `codex_cli` import or `chatgpt-plan` reference at all (grepped — zero hits), so there is no engine to select yet. (G74 rung (b) is a different, unrelated mechanism — the in-session MCP agent doing consolidation itself via a future `cicada_consolidate` tool — and is not about a CLI-backed Sleep engine; do not cite it here.) The GET response's `candidates` list still includes a `codex` row (`available: false`) so the segmented picker can show and explain it.
- **R6 — the Sleep engine mutation is a plain APIClient round trip, not a `Store.perform` Mutation.** `ScheduleConfig` (the closest sibling — also settings-shaped, also not ETag'd, also not an SSE-pushed domain) already uses exactly this shape (`SleepViewModel.updateSchedule` — plain `try await APIClient.shared.updateSchedule(new)`, no optimistic-apply/rollback machinery). `/sleep/engine` has the same properties (no `Store` domain, no ETag, no SSE event), so `SleepEngineViewModel` copies that pattern rather than inventing a `SetSleepEngine` `Mutation` for a page nothing else observes.
- **R7 — `SettingsSection`/`IntegrationCategory` raw values are machine keys, never the display string.** `case plansAndKeys` (implicit raw value `"plansAndKeys"`), with `var title: String` computed from `Copy.*` — never `case plansAndKeys = "Plans & keys"`, which would trip `CopyConstantsTests.testNoViewRetypesAPointerLiteral`'s banned-literal scan. This also decouples `@AppStorage("cicada.settingsSection")`'s persisted identity from a future copy rename.
- **R8 — Integrations' state line is a dedicated pure formatter, not `SourceChannel.detail`.** The backend's `detail` string differs in shape per channel kind (bookmarks say "X bookmarks · synced …", a connector says "+N this sync · synced …", a feed says "N feeds · polled …") — fine for the existing Sources grid, but Integrations groups all of them in one visual language, so a single `IntegrationRowState.line(_:now:)` composes connected-state, a relative last-sync time, the count and the error into one consistent sentence.
- **R9 — the Feed hand-off is a two-field `AppRouter`, not a `NotificationCenter` post.** CLAUDE.md's Companion App section confirms "The app has no NotificationCenter-based cross-window messaging today" — `AppRouter` is a small `@Observable @MainActor` class (`pendingTab`, `pendingAddSource`) injected into both scenes via `.environment`, matching how every other cross-view-model coordination in this app already works (thin observed classes, not notifications).

## File map

```
api/models/schemas.py                                    [edit] +SleepEngineCandidate/Choice/Preview(s)/Response
api/services/engine_select.py                             [edit] prefs rung + model overrides
api/services/agent_engine.py                              [edit] +is_valid_model_id
api/services/sleep_engine_prefs.py                        [new]  GET/PUT /sleep/engine business logic
api/routers/sleep.py                                       [edit] +GET/PUT /sleep/engine
api/tests/test_engine_select.py                            [edit] +prefs-rung precedence tests
api/tests/test_sleep_engine_prefs.py                       [new]  GET/PUT /sleep/engine router+service tests

app/CicadaApp/Sources/CicadaApp/Theme/Copy.swift                              [edit] schedule*->sleepSettings*, +integrations*
app/CicadaApp/Sources/CicadaApp/Views/Sleep/HowSleepWorks.swift               [edit] pointer rename
app/CicadaApp/Sources/CicadaApp/Views/Sleep/StudyListCard.swift               [edit] pointer rename
app/CicadaApp/Sources/CicadaApp/Views/Settings/SettingsSection.swift          [new]  sidebar section enum
app/CicadaApp/Sources/CicadaApp/Views/Settings/SettingsScene.swift            [edit] TabView -> NavigationSplitView
app/CicadaApp/Sources/CicadaApp/Views/Settings/SettingsSleepView.swift        [edit] engineCard -> EngineCard; rename
app/CicadaApp/Sources/CicadaApp/Views/Settings/EngineCard.swift               [new]  the G122 card
app/CicadaApp/Sources/CicadaApp/ViewModels/SleepEngineViewModel.swift         [new]
app/CicadaApp/Sources/CicadaApp/Models/SleepEngine.swift                      [new]  wire structs
app/CicadaApp/Sources/CicadaApp/Services/APIClient.swift                     [edit] +fetchSleepEngine/updateSleepEngine
app/CicadaApp/Sources/CicadaApp/Views/Settings/IntegrationsView.swift        [new]  the G126 page
app/CicadaApp/Sources/CicadaApp/Models/IntegrationCategory.swift             [new]  category table + row state
app/CicadaApp/Sources/CicadaApp/Support/AppRouter.swift                      [new]
app/CicadaApp/Sources/CicadaApp/Views/Feed/FeedView.swift                    [edit] consume router.pendingAddSource
app/CicadaApp/Sources/CicadaApp/ContentView.swift                            [edit] consume router.pendingTab
app/CicadaApp/Sources/CicadaApp/CicadaApp.swift                              [edit] inject AppRouter into both scenes
app/CicadaApp/Tests/CicadaAppTests/CopyConstantsTests.swift                  [edit] renamed pair
app/CicadaApp/Tests/CicadaAppTests/SettingsSectionTests.swift                [new]
app/CicadaApp/Tests/CicadaAppTests/EngineCardTests.swift                    [new]
app/CicadaApp/Tests/CicadaAppTests/IntegrationsViewTests.swift              [new]
app/CicadaApp/Tests/CicadaAppTests/AppRouterTests.swift                     [new]

CLAUDE.md                                                  [edit] Companion App → Navigation
docs/goals/memory-evolution.md                             [edit] G122 -> done, G126 -> page shipped
docs/goals/TODO.md                                          [edit] handoff header
docs/goals/working-method.md                                [edit] §3 queue note
```

---

## Task 1 — Backend: `GET/PUT /sleep/engine` (G122)

**Files:** `api/models/schemas.py`, `api/services/engine_select.py`, `api/services/agent_engine.py`, `api/services/sleep_engine_prefs.py` (new), `api/routers/sleep.py`, `api/tests/test_engine_select.py`, `api/tests/test_sleep_engine_prefs.py` (new).

**Interfaces:**

```python
# api/services/agent_engine.py — expose the existing charset check publicly
def is_valid_model_id(model: str) -> bool:
    return bool(model) and bool(_MODEL_ID_RE.match(model))

# api/services/engine_select.py — new module-level constant + helper
SLEEP_ENGINE_PREF_KEY = "sleep-engine"

def _prefs_mode(registry) -> str | None: ...   # defensive like use_for_sleep()
def _model_overrides(registry, mode: str) -> dict: ...

# api/services/sleep_engine_prefs.py
PREF_KEY = engine_select.SLEEP_ENGINE_PREF_KEY
VALID_MODES = ("auto", "agent", "byok", "local")

async def build_response(settings: Settings, reg: Registry) -> SleepEngineResponse: ...
def validate_and_write(body: SleepEngineChoice, reg: Registry) -> None: ...  # raises HTTPException(422)
```

```python
# api/models/schemas.py
class SleepEngineCandidate(CamelModel):
    id: str
    label: str
    available: bool = False
    connected: bool = False
    models: list[str] = Field(default_factory=list)
    detail: Optional[str] = None

class SleepEnginePreview(CamelModel):
    engine: str
    model: str
    why: str

class SleepEnginePreviews(CamelModel):
    manual: SleepEnginePreview
    scheduled: SleepEnginePreview

class SleepEngineResponse(CamelModel):
    mode: str
    model: str
    disambiguation_model: str
    source: str  # "env" | "prefs" | "default"
    candidates: list[SleepEngineCandidate]
    preview: SleepEnginePreviews

class SleepEngineChoice(CamelModel):
    mode: str
    model: Optional[str] = None
    disambiguation_model: Optional[str] = None
```

### Steps

- [ ] **1.1 Failing tests first — `engine_select` prefs rung.** Append to `api/tests/test_engine_select.py`:
  - `test_prefs_mode_applies_when_env_is_not_explicit`: `_FakeRegistry(prefs={"sleep-engine": {"mode": "local"}})`, `Settings()` (no `llm_mode` kwarg) → `resolve_llm_mode` returns `("local", why-mentions-"Settings")`.
  - `test_prefs_agent_still_degrades_to_byok_on_a_scheduled_cycle` (ruling 4/R3): same prefs but `mode: "agent"`, `user_triggered=False` → `("byok", ...)`.
  - `test_prefs_agent_wins_on_a_user_triggered_cycle_when_claude_is_connected`: prefs `mode: "agent"`, registry `connected=(CLAUDE_CONNECTION_ID,)`, `user_triggered=True` → `("agent", ...)`.
  - `test_explicit_env_ignores_prefs_entirely` (R4): `Settings(llm_mode="byok")` (explicit) + prefs `{"sleep-engine": {"mode": "agent"}}` → still resolves through the normal byok/auto probe path, never short-circuits to `"agent"` from prefs.
  - `test_duck_typed_settings_never_touches_the_registry_for_prefs`: reuse the existing `_Boom`-style registry (raises on `.prefs()`) with a bare `SimpleNamespace(llm_mode=None)` (no `model_fields_set`) → resolves to `"byok"` without raising (proves R2's shape gate).
  - Run: `api/.venv/bin/python -m pytest api/tests/test_engine_select.py -q -p no:cacheprovider` — new tests fail (function doesn't exist yet / behavior not implemented).
- [ ] **1.2 Implement the `engine_select.py` rung.** First, update the module's own top-of-file docstring (the "Precedence, and the reason for each rung" list, rungs 1-3) to insert this as a new rung between 1 ("`llm_mode` of `"agent"` or `"local"`") and 2 ("`"auto"`") — a bare summary sentence naming `SLEEP_ENGINE_PREF_KEY`/R2's `model_fields_set` gate and pointing at G122 — so the docstring stays the accurate map of the function it describes rather than going stale the moment this task lands. Add `SLEEP_ENGINE_PREF_KEY = "sleep-engine"` near the existing pref constants. Add `_prefs_mode(registry) -> str | None` (try/except like `use_for_sleep`, returns the pref's `"mode"` only if it's one of the four valid values). In `resolve_llm_mode`, replace the top of the function:
  ```python
  configured = (getattr(settings, "llm_mode", None) or "byok").strip().lower()
  has_fields_set = hasattr(settings, "model_fields_set")
  env_explicit = has_fields_set and "llm_mode" in settings.model_fields_set
  if has_fields_set and not env_explicit:
      if registry is None:
          from api.services.connections.registry import get_registry
          registry = get_registry(settings)
      pref_mode = _prefs_mode(registry)
      if pref_mode is not None:
          configured = pref_mode
  if configured in ("agent", "local"):
      if configured == "agent" and not env_explicit and not user_triggered:
          return "byok", "scheduled cycle — Sleep engine selection is user-triggered only"
      return configured, (
          f"CICADA_LLM_MODE={configured}" if env_explicit
          else f"Sleep engine set to {configured!r} in Settings"
      )
  ```
  (the existing `if not hasattr(settings, "model_copy"): ...` / `if not user_triggered: ...` / `if configured not in (...)` lines below are unchanged — they still gate the `auto`/`byok` path exactly as before). Add `_model_overrides(registry, mode) -> dict` (maps `agent -> (agent_model, agent_disambiguation_model)`, `local -> (ollama_model, None)`, `byok -> (litellm_model, litellm_disambiguation_model)`; returns `{}` for `auto`, `None` registry, or an unreadable prefs file). In `resolve_settings`, after computing `mode, why`, gate a second read exactly as R4 requires:
  ```python
  if not hasattr(settings, "model_copy"):
      return settings, why           # M2 guard, unchanged in spirit
  env_explicit = hasattr(settings, "model_fields_set") and "llm_mode" in settings.model_fields_set
  updates = {}
  if mode != configured:
      updates["llm_mode"] = mode
  if not env_explicit:
      updates.update(_model_overrides(registry, mode))
  if not updates:
      return settings, why
  return settings.model_copy(update=updates), why
  ```
  (this replaces the whole existing `if mode == configured or not hasattr(...): return settings, why` / `return settings.model_copy(update={"llm_mode": mode}), why` pair — `updates` empty is exactly the old `mode == configured` case when no model override exists either). Run **the full existing file** to confirm zero regressions, then the new tests from 1.1 — all green.
- [ ] **1.3 `agent_engine.is_valid_model_id` + its test.** One-line public wrapper around `_MODEL_ID_RE` (docstring: "the same charset `build_argv` enforces — exposed so `sleep_engine_prefs` can validate a PUT body without reaching into a private name"). Add `test_is_valid_model_id_matches_build_argvs_charset` to `api/tests/test_agent_engine.py` (valid: `"sonnet"`, `"claude-sonnet-5"`, `"ollama/llama3.1:8b"`; invalid: `""`, `"-oops"`, `"rm -rf"`).
- [ ] **1.4 Failing tests — `sleep_engine_prefs` + router.** New `api/tests/test_sleep_engine_prefs.py`, `client` fixture mirroring `test_connections_api.py`'s (same `CICADA_HOME`/`CICADA_MEMORY_PATH` tmp-path pattern, same `fake_run`/`_ollama_fetch_tags` patches):
  - `test_get_default_shape`: fresh install → `mode == "byok"`, `source == "default"`, `candidates` has exactly 5 rows with ids `{auto, agent, codex, local, byok}`, `codex.available is False` and its `detail` says Sleep can't run on it yet, `preview.manual` and `preview.scheduled` both present with a `why` string each.
  - `test_put_writes_prefs_and_get_reflects_them`: `PUT {"mode": "local", "model": "llama3.1"}` → `200`, then `GET` → `mode == "local"`, `source == "prefs"`, `model == "llama3.1"`.
  - `test_put_rejects_codex_and_bogus_mode`: `PUT {"mode": "codex"}` and `PUT {"mode": "sonnet"}` → both `422`.
  - `test_put_rejects_an_invalid_agent_model`: `PUT {"mode": "agent", "model": "-oops"}` → `422`.
  - `test_put_accepts_any_nonempty_ollama_tag`: `PUT {"mode": "local", "model": "custom:latest"}` → `200`.
  - `test_switching_mode_clears_the_previous_modes_stale_model`: `PUT {"mode": "local", "model": "llama3.1"}`, then `PUT {"mode": "agent"}` (mode only, no model) → `GET`'s top-level `model` is NOT `"llama3.1"` (it falls back to `settings.agent_model`'s default, `"sonnet"`) — proves a Local-mode Ollama tag can never survive a mode switch and get misread as an Agent-mode Claude alias.
  - `test_scheduled_preview_never_shows_the_plan_when_only_prefs_chose_it` (ruling 4, the point of the whole feature): after `PUT {"mode": "agent"}` with Claude probed connected, `GET`'s `preview.scheduled.engine == "litellm"` while `preview.manual.engine == "claude-cli"`.
  - `test_prefs_file_is_0600`: after any `PUT`, `oct((tmp_path/"home"/"connections.json").stat().st_mode)[-3:] == "600"`.
  - `test_get_never_returns_a_price_or_token_field`: `"price" not in resp.text.lower()` and `"token" not in resp.text.lower()` (G124 rail, cheap regression net).
  - Run — all fail (endpoints don't exist).
- [ ] **1.5 Implement `api/services/sleep_engine_prefs.py`.** `_candidates(settings, reg)` — awaits `reg.statuses(fresh=False)`, builds the 5 rows (`auto` static; `agent`/`local` from the matching `ConnectionStatus` plus, for `agent`, `["sonnet","haiku","opus"]` + `settings.agent_model` if not already listed, and for `local`, tags from `registry_module._ollama_fetch_tags(settings.ollama_base_url)` wrapped in try/except → `[]`; `codex` and `byok` static). `_configured_choice(settings, reg)` mirrors the env/prefs precedence from 1.2 *without* the connectivity probe (source of the GET's `mode`/`source` fields). `build_response` assembles `SleepEngineResponse`, calling `engine_select.resolve_settings(settings, reg, user_triggered=True|False)` twice for `preview.manual`/`preview.scheduled`, deriving each preview's `model` from `agent_engine.model_for_stage(resolved, None)` / `resolved.ollama_model` / `resolved.litellm_model` keyed off `engine_select.engine_label(resolved)`. `validate_and_write` checks `body.mode in VALID_MODES` (422 otherwise), validates `model`/`disambiguation_model` per-mode via `agent_engine.is_valid_model_id` (agent) or non-blank (local), then three `reg.set_pref(PREF_KEY, ...)` calls gated by `"model" in body.model_fields_set` / `"disambiguation_model" in body.model_fields_set` (mirrors `connections.py`'s `"tier" in body.model_fields_set` idiom) — `mode` is always written (required field). **Cross-mode staleness guard:** `model`/`disambiguation_model` share ONE untyped string slot per the `sleep-engine` pref entry, but a Local-mode Ollama tag and an Agent-mode Claude alias are not interchangeable — `_model_overrides` (1.2) reinterprets whatever string sits in that slot as belonging to whichever mode is CURRENTLY selected, with no mode tag of its own. So before writing, read the mode already on disk (`reg.prefs().get(PREF_KEY, {}).get("mode")`); when `body.mode` differs from it AND the body itself doesn't also supply a fresh value for that field, clear it (`reg.set_pref(PREF_KEY, "model", None)` / same for `disambiguation_model` — `None` removes the key per `Registry.set_pref`'s own semantics) instead of leaving the previous mode's value to be silently misapplied as this mode's `--model`/API id on the next resolution. A PUT that supplies BOTH the new mode and a new model in the same call is unaffected (its own value simply overwrites).
- [ ] **1.6 Wire the router.** In `api/routers/sleep.py`, import `sleep_engine_prefs` and the new schemas, add:
  ```python
  @router.get("/sleep/engine", response_model=SleepEngineResponse)
  async def get_sleep_engine(settings: Settings = Depends(get_settings)):
      return await sleep_engine_prefs.build_response(settings, get_registry(settings))

  @router.put("/sleep/engine", response_model=SleepEngineResponse)
  async def put_sleep_engine(body: SleepEngineChoice, settings: Settings = Depends(get_settings)):
      reg = get_registry(settings)
      sleep_engine_prefs.validate_and_write(body, reg)
      return await sleep_engine_prefs.build_response(settings, reg)
  ```
  (`get_registry` imported from `api.services.connections.registry`, same module `engine_select` itself already imports lazily). Run 1.1, 1.3, 1.4 together, then the **full suite**.
- [ ] **1.7 Verify + commit.**
  ```
  cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/settings
  api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider
  ```
  0 failures (or the one documented order-dependent case, re-run alone and report both). Stage exactly: `api/models/schemas.py api/services/engine_select.py api/services/agent_engine.py api/services/sleep_engine_prefs.py api/routers/sleep.py api/tests/test_engine_select.py api/tests/test_sleep_engine_prefs.py api/tests/test_agent_engine.py`. Commit: `feat(G122): GET/PUT /sleep/engine — engine & model picker, prefs-first`.

---

## Task 2 — Settings becomes a five-section sidebar

**Files:** `Views/Settings/SettingsSection.swift` (new), `Views/Settings/SettingsScene.swift`, `Theme/Copy.swift`, `Views/Sleep/HowSleepWorks.swift`, `Views/Sleep/StudyListCard.swift`, `Tests/CicadaAppTests/CopyConstantsTests.swift`, `Tests/CicadaAppTests/SettingsSectionTests.swift` (new).

**Interfaces:**

```swift
enum SettingsSection: String, CaseIterable, Identifiable {
    case general, sleep, integrations, agents, plansAndKeys
    var id: String { rawValue }
    var title: String { /* Copy.* per case — R7 */ }
    var icon: String { /* SF symbol per case */ }
    static func restored(from raw: String?) -> SettingsSection
}
```

### Steps

- [ ] **2.1 Failing test first.** New `Tests/CicadaAppTests/SettingsSectionTests.swift`:
  ```swift
  func testRestoredFallsBackToGeneral() {
      XCTAssertEqual(SettingsSection.restored(from: nil), .general)
      XCTAssertEqual(SettingsSection.restored(from: "bogus"), .general)
      XCTAssertEqual(SettingsSection.restored(from: "sleep"), .sleep)
  }
  func testEveryTitleComesFromCopy() {
      XCTAssertEqual(SettingsSection.general.title, Copy.general)
      XCTAssertEqual(SettingsSection.sleep.title, Copy.sleepSettings)
      XCTAssertEqual(SettingsSection.integrations.title, Copy.integrations)
      XCTAssertEqual(SettingsSection.agents.title, Copy.agents)
      XCTAssertEqual(SettingsSection.plansAndKeys.title, Copy.plansAndKeys)
  }
  func testSettingsSceneUsesANavigationSplitView() throws {
      let url = URL(fileURLWithPath: #filePath)
          .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
          .appendingPathComponent("Sources/CicadaApp/Views/Settings/SettingsScene.swift")
      let text = try String(contentsOf: url, encoding: .utf8)
      XCTAssertTrue(text.contains("NavigationSplitView"))
  }
  ```
  `swift test --filter SettingsSectionTests` fails (types/constants don't exist).
- [ ] **2.2 Rename in `Copy.swift`** (R7 — machine keys stay out of Copy; these ARE the Copy definitions, so plain string literals here are correct and exempted by `CopyConstantsTests`'s own `file.lastPathComponent == "Copy.swift"` skip):
  - `schedule = "Schedule"` → `sleepSettings = "Sleep"`.
  - `settingsSchedule` → `settingsSleep = "\(settings) → \(sleepSettings)"`.
  - `scheduleSubtitle = "When Sleep runs on its own, and what powers it."` → `sleepSettingsSubtitle = "Who runs the nightly cycle, and when."` (must not contain "sleep" — the new title — per `testSubtitlesAreShortAndDoNotRepeatTheirTitle`).
  - `changeInSettingsSchedule` → `changeInSettingsSleep = "Change in \(settingsSleep)"`.
  - Add `integrations = "Integrations"`, `settingsIntegrations = "\(settings) → \(integrations)"`, `integrationsSubtitle = "Every app connected to Cicada, in one place."`.
- [ ] **2.3 Update the four outside call sites**: `HowSleepWorks.swift:66,69` (`Copy.settingsSchedule` → `Copy.settingsSleep`, update the doc comment too), `StudyListCard.swift:224` (`Copy.changeInSettingsSchedule` → `Copy.changeInSettingsSleep`). `SettingsSleepView.swift`'s own `Copy.schedule`/`Copy.scheduleSubtitle` use is replaced in Task 3 (left alone here would fail to compile once Copy.swift no longer has those names — so touch line 39's two names now, minimally: `PageHeader(title: Copy.sleepSettings, subtitle: Copy.sleepSettingsSubtitle) {}`, no other change to that file yet).
- [ ] **2.4 Update `CopyConstantsTests.swift:41`**: `(Copy.schedule, Copy.scheduleSubtitle)` → `(Copy.sleepSettings, Copy.sleepSettingsSubtitle)`; add `(Copy.integrations, Copy.integrationsSubtitle)` to the same pairs array (Integrations is a new page, its subtitle earns the same shape test).
- [ ] **2.5 Write `SettingsSection.swift`** per the interface above, `icon` per case: `general -> "gearshape"`, `sleep -> "moon.zzz"`, `integrations -> "puzzlepiece.extension"`, `agents -> "cable.connector"`, `plansAndKeys -> "creditcard"`.
- [ ] **2.6 Rewrite `SettingsScene.swift`**:
  ```swift
  struct SettingsScene: View {
      @AppStorage("cicada.settingsSection") private var sectionRaw = SettingsSection.general.rawValue
      @State private var selection: SettingsSection = .general

      var body: some View {
          NavigationSplitView {
              List(SettingsSection.allCases, selection: $selection) { section in
                  Label(section.title, systemImage: section.icon).tag(section)
              }
              .navigationSplitViewColumnWidth(min: 160, ideal: 180, max: 220)
          } detail: {
              detailView
                  .frame(maxWidth: .infinity, maxHeight: .infinity)
                  .background(CicadaTheme.background)
          }
          .frame(width: 900, height: 640)
          .onAppear { selection = SettingsSection.restored(from: sectionRaw) }
          .onChange(of: selection) { _, newValue in sectionRaw = newValue.rawValue }
      }

      @ViewBuilder private var detailView: some View {
          switch selection {
          case .general: SettingsGeneralView()
          case .sleep: SettingsSleepView()
          case .integrations: IntegrationsView()
          case .agents: ConnectView()
          case .plansAndKeys: ConnectionsView()
          }
      }
  }
  ```
  `IntegrationsView` doesn't exist yet, so this task also creates a minimal stub — a **new** `Views/Settings/IntegrationsView.swift` containing only `struct IntegrationsView: View { var body: some View { PageHeader(title: Copy.integrations, subtitle: Copy.integrationsSubtitle) {} } }` — so the branch builds at the end of this task. Task 4 fleshes out this same file in place; it never creates a second one.
- [ ] **2.7 Build + test.**
  ```
  cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/settings/app/CicadaApp
  swift build 2>&1 | tail -5
  swift test 2>&1 | tail -20
  ```
  0 failures.
- [ ] **2.8 Commit.** Stage: `Sources/CicadaApp/Theme/Copy.swift Sources/CicadaApp/Views/Settings/SettingsSection.swift Sources/CicadaApp/Views/Settings/SettingsScene.swift Sources/CicadaApp/Views/Settings/IntegrationsView.swift Sources/CicadaApp/Views/Sleep/HowSleepWorks.swift Sources/CicadaApp/Views/Sleep/StudyListCard.swift Sources/CicadaApp/Views/Settings/SettingsSleepView.swift Tests/CicadaAppTests/CopyConstantsTests.swift Tests/CicadaAppTests/SettingsSectionTests.swift`. Commit: `feat(G122/G126): Settings becomes a five-section sidebar`.

---

## Task 3 — Settings → Sleep: the `EngineCard`

**Files:** `Models/SleepEngine.swift` (new), `Services/APIClient.swift`, `ViewModels/SleepEngineViewModel.swift` (new), `Views/Settings/EngineCard.swift` (new), `Views/Settings/SettingsSleepView.swift`, `CicadaApp.swift`, `Tests/CicadaAppTests/EngineCardTests.swift` (new).

**Interfaces:**

```swift
// Models/SleepEngine.swift — tolerant mirrors of Task 1's schemas
struct SleepEngineCandidate: Codable, Identifiable, Hashable { let id, label: String; let available, connected: Bool; let models: [String]; let detail: String? }
struct SleepEnginePreview: Codable, Hashable { let engine, model, why: String }
struct SleepEnginePreviews: Codable, Hashable { let manual, scheduled: SleepEnginePreview }
struct SleepEngineResponse: Codable, Hashable { let mode, model, disambiguationModel, source: String; let candidates: [SleepEngineCandidate]; let preview: SleepEnginePreviews? }

enum OllamaGuideState { case notInstalled, notRunning, noModel, ready
    static func from(candidate: SleepEngineCandidate) -> OllamaGuideState
    var command: String? // "brew install ollama" / "ollama serve" / "ollama pull llama3.1" / nil
}

// ViewModels/SleepEngineViewModel.swift
@Observable @MainActor final class SleepEngineViewModel {
    var response: SleepEngineResponse?
    var errorMessage: String?
    func load() async
    func set(mode: String, model: String?, disambiguationModel: String?) async
}
```

### Steps

- [ ] **3.1 Failing tests first.** New `Tests/CicadaAppTests/EngineCardTests.swift`:
  - `testOllamaGuideStateProgression`: a candidate with `available=false` → `.notInstalled` (`command == "brew install ollama"`); `available=true, connected=false` → `.notRunning` (`command == "ollama serve"`); `available=true, connected=true, models=[]` → `.noModel` (`command == "ollama pull llama3.1"`); `models=["llama3.1"]` → `.ready` (`command == nil`).
  - `testPreviewLineFormatting`: a pure `EngineCard.previewLine(_ preview: SleepEnginePreview, label: String) -> String` (e.g. `"Next cycle you start: Claude Code (your plan) · sonnet"` / `"Nightly schedule: API key · gpt-5.4-mini"` — the engine half is exactly `Copy.engineLabel(preview.engine)`'s existing three-way mapping, not a fresh coinage), using `Copy.engineLabel` for the human word.
  - `testDecodesAnOlderPayloadMissingCandidatesAndPreview`: decode `{"mode":"byok","model":"gpt-5.4-mini","disambiguationModel":"gpt-5.4-nano","source":"default"}` (no `candidates`/`preview` keys) → succeeds with `candidates == []` and `preview == nil` (tolerant `init(from:)` on `SleepEngineResponse`; `preview` becomes `Optional` for this reason even though Task 1's backend always sends it — an older cached JSON on disk must not crash decode).
  - Run `swift test --filter EngineCardTests` — fails.
- [ ] **3.2 `Models/SleepEngine.swift`.** The four structs above; `SleepEngineResponse.preview: SleepEnginePreviews?` with a tolerant `init(from:)` (`decodeIfPresent` for `candidates`/`preview`, defaulting `[]`/`nil`); `OllamaGuideState.from(candidate:)` implements the four-state ladder from 3.1 as a pure function.
- [ ] **3.3 `APIClient` additions**: `func fetchSleepEngine() async throws -> SleepEngineResponse { try await get("/sleep/engine") }` and `func updateSleepEngine(mode: String, model: String?, disambiguationModel: String?) async throws -> SleepEngineResponse` hand-building the PUT body dict (same reasoning as `updateSchedule`'s own doc comment: the `put<T>` helper takes `[String: Any]`, and omitting a `nil` field from the dict entirely — rather than sending JSON `null` — matches the backend's `"model" in body.model_fields_set` omitted-vs-null distinction).
- [ ] **3.4 `SleepEngineViewModel`** — `load()` calls `fetchSleepEngine()` into `response`, catching into `errorMessage`; `set(mode:model:disambiguationModel:)` calls `updateSleepEngine(...)` and assigns the echoed response back into `response` (server is authoritative — no local optimistic mutation, matching R6's "plain round trip" ruling).
- [ ] **3.5 `EngineCard.swift`** — a `glassCard()` matching `SettingsSleepView`'s existing card style: a segmented `Picker` over `response.candidates` (label from each candidate; the `codex` option rendered `.disabled(true)`), the selected candidate's live state line (`connected`/`available`/`detail`), a model field (`Picker` over `candidate.models` + free-text `TextField` for `agent`, gated by `agent_engine`-style charset — client-side hint only, the backend is authoritative; a `Picker` over `candidate.models` for `local` plus a `CommandBox`-style `Text` showing `OllamaGuideState.from(candidate:).command` when not `.ready`; a `Text` pointing at `Copy.settingsPlansAndKeys` for `byok`), then two preview lines built via `EngineCard.previewLine(_:label:)` for `preview.manual`/`preview.scheduled`, plus a one-line caption **only when the two differ** ("Scheduled cycles never spend plan quota unless `CICADA_LLM_MODE` is set in `api/.env`.") — never a price, never a token count.
- [ ] **3.6 `SettingsSleepView.swift`**: replace the existing private `engineCard` computed property (the one that currently just points at Plans & keys) with `EngineCard()` (own `@Environment`/`@State` of its `SleepEngineViewModel`, loaded in the view's existing `.task`). Delete the now-dead "Which model powers Sleep is set on the Claude plan's connection card" paragraph — it is no longer true.
- [ ] **3.7 `CicadaApp.swift`**: construct `_sleepEngineVM = State(initialValue: SleepEngineViewModel())` (no `Store` dependency — R6) alongside the other view models in `init()`, inject `.environment(sleepEngineVM)` into both the `WindowGroup` and `Settings` scenes (the Sleep page itself doesn't need it, but Settings does, and a stray environment miss is a silent crash-free blank card rather than a compile error, so inject everywhere other VMs already are for consistency).
- [ ] **3.8 Build + test.** `swift build 2>&1 | tail -5` and `swift test 2>&1 | tail -20` — 0 failures.
- [ ] **3.9 Commit.** Stage: `Sources/CicadaApp/Models/SleepEngine.swift Sources/CicadaApp/Services/APIClient.swift Sources/CicadaApp/ViewModels/SleepEngineViewModel.swift Sources/CicadaApp/Views/Settings/EngineCard.swift Sources/CicadaApp/Views/Settings/SettingsSleepView.swift Sources/CicadaApp/CicadaApp.swift Tests/CicadaAppTests/EngineCardTests.swift`. Commit: `feat(G122): Settings → Sleep gets the engine & model picker`.

---

## Task 4 — Settings → Integrations page (G126)

**Files:** `Models/IntegrationCategory.swift` (new), `Support/AppRouter.swift` (new), `Views/Settings/IntegrationsView.swift` (fleshed out from Task 2's stub), `Views/Feed/FeedView.swift`, `ContentView.swift`, `CicadaApp.swift`, `Tests/CicadaAppTests/IntegrationsViewTests.swift` (new), `Tests/CicadaAppTests/AppRouterTests.swift` (new).

**Interfaces:**

```swift
enum IntegrationCategory: String, CaseIterable, Identifiable {
    case chatAndAgents, browsers, socialAndSaved, feedsAndCalendars, messaging, filesAndImports
    var id: String { rawValue }
    var title: String { /* literal here is fine — not a Copy-owned cross-page pointer */ }
    static func of(channelId: String) -> IntegrationCategory
}

enum IntegrationRowState {
    static func line(_ channel: SourceChannel, now: Date = Date()) -> String
}

@Observable @MainActor final class AppRouter {
    var pendingTab: AppTab?
    var pendingAddSource: AddSourceTile?
    func routeToFeedAddSource(_ tile: AddSourceTile)
    @discardableResult func consumeAddSource() -> AddSourceTile?
}
```

### Steps

- [ ] **4.1 Failing tests first.** New `Tests/CicadaAppTests/IntegrationsViewTests.swift`:
  ```swift
  func testEveryChannelIdHasACategory() {
      // Mirrors api/services/channel_registry.py::CHANNEL_IDS verbatim (2312887) —
      // a 14th id added later needs this list AND the switch updated together.
      let ids: [(String, IntegrationCategory)] = [
          ("chat-export:claude", .chatAndAgents), ("chat-export:chatgpt", .chatAndAgents),
          ("chrome-bookmarks", .browsers), ("safari-bookmarks", .browsers), ("safari-tabs", .browsers),
          ("notes", .filesAndImports),
          ("rss", .feedsAndCalendars), ("calendar", .feedsAndCalendars),
          ("pinterest", .socialAndSaved), ("reddit", .socialAndSaved), ("x", .socialAndSaved),
          ("telegram", .messaging), ("files", .filesAndImports),
      ]
      for (id, expected) in ids {
          XCTAssertEqual(IntegrationCategory.of(channelId: id), expected, id)
      }
  }
  func testHarnessRowsComeFromSourcesOverview() {
      let overview = [SourceOverview(id: "claude-code", label: "Claude Code", kind: .harness),
                       SourceOverview(id: "chrome-bookmarks", label: "Chrome", kind: .browser)]
      XCTAssertEqual(IntegrationHarnessRows.rows(from: overview).map(\.id), ["claude-code"])
  }
  func testRowStateLine() {
      let now = Date(timeIntervalSince1970: 1_800_000_000)
      let connected = SourceChannel(id: "chrome-bookmarks", label: "Chrome bookmarks", connected: true,
                                     count: 12, lastSync: iso(now.addingTimeInterval(-3600)))
      XCTAssertTrue(IntegrationRowState.line(connected, now: now).contains("12 items"))
      let disconnected = SourceChannel(id: "x", label: "X", connected: false)
      XCTAssertEqual(IntegrationRowState.line(disconnected, now: now), "Not connected")
      let errored = SourceChannel(id: "rss", label: "RSS", connected: true, lastError: "401 Unauthorized")
      XCTAssertTrue(IntegrationRowState.line(errored, now: now).contains("401 Unauthorized"))
  }
  ```
  (`iso(_:)` a tiny local helper formatting an ISO8601 string.) New `Tests/CicadaAppTests/AppRouterTests.swift`:
  ```swift
  @MainActor func testRouteToFeedStagesTileAndTab() {
      let router = AppRouter()
      router.routeToFeedAddSource(.instagram)
      XCTAssertEqual(router.pendingTab, .feed)
      XCTAssertEqual(router.pendingAddSource, .instagram)
  }
  @MainActor func testConsumeClearsAfterOneRead() {
      let router = AppRouter()
      router.routeToFeedAddSource(.youtube)
      XCTAssertEqual(router.consumeAddSource(), .youtube)
      XCTAssertNil(router.pendingAddSource)
      XCTAssertNil(router.consumeAddSource())
  }
  ```
  Run both new files — fail (types don't exist).
- [ ] **4.2 `IntegrationCategory.swift`** — the `of(channelId:)` switch per the test table above (`default` case, unreachable given the test's exhaustive list, returns `.filesAndImports` rather than crashing — a future 14th channel id degrades safely instead of taking the app down); `title` per case (`"Chat & agents"`, `"Browsers"`, `"Social & saved"`, `"Feeds & calendars"`, `"Messaging"`, `"Files & imports"` — plain literals, since `CopyConstantsTests`'s banned list is specifically cross-page *pointers*, and these are page-local section headers with no `Copy.*` twin anywhere else to drift from). `IntegrationRowState.line(_:now:)` per R8 (connected → `[relative last-sync, "\(count) item(s)" if count>0]` joined by `" · "`, falling back to `"Connected"` if both are empty, then `" · \(lastError)"` appended when present; not connected → literal `"Not connected"`). `IntegrationHarnessRows.rows(from:) -> [SourceOverview]` — one-line filter on `.kind == .harness`.
- [ ] **4.3 `Support/AppRouter.swift`** per the interface (R9): `routeToFeedAddSource` sets both fields together (a `pendingAddSource` with no matching tab-switch would stage a sheet nobody ever sees); `consumeAddSource()` reads-then-clears in one call (`defer { pendingAddSource = nil }`) so a caller can never re-consume a stale tile.
- [ ] **4.4 Flesh out `IntegrationsView.swift`** (replacing Task 2's one-line stub in place): `@Environment(Store.self) private var store`, `@Environment(AppRouter.self) private var router`; group `store.channels.value ?? []` by `IntegrationCategory.of(channelId:)` in `IntegrationCategory.allCases` order, append `IntegrationHarnessRows.rows(from: store.sourcesOverview.value ?? [])` under `.chatAndAgents`, and append one informational row per export-only social platform (`AddSourceTile.instagram, .youtube, .linkedin, .tiktok`) under `.socialAndSaved` with a trailing `Button("Import in Feed →") { router.routeToFeedAddSource(tile) }`. Each real-channel row: `OriginMark`/logo (28pt, reusing `AddSourceTile.forChannel(channel.id)`'s mark when present), `channel.label`, `IntegrationRowState.line(channel)` (danger-colored when `channel.lastError != nil`), and ONE trailing action per `channel.actions`: `"connect"` → a `.popover` presenting `ConnectorSetupPanel(connectorId: channel.id, vendors: AddSourceTile.forChannel(channel.id)?.vendors ?? [], vendor: $vendor)` — per spec Track C §3 (only reachable for the three connector ids, which are the only ones `channel_registry` ever gives `actions: ["connect"]`); `"sync"`/`"poll"` → `Button { Task { try? await ChannelActions.sync/poll(channel.id, ...) } }`; `"disconnect"` → covered inside the same `ConnectorSetupPanel` popover, not a second button. **`@State` can only live on a `View`**, so each real-channel row must be its own small child `View` struct (e.g. `IntegrationChannelRow`, mirroring `ConnectedChannelRow`'s own `@State private var isHovered`) carrying its own `@State private var vendor: WalkthroughVendor = .claude` — `IntegrationsView` cannot declare this state once and reuse it across a `ForEach`, since neither existing `ConnectorSetupPanel` call site (`AddSourceSheet.swift:583`'s own `@State`, `ConnectedChannelsStrip`'s full-sheet hand-off) hands the panel a binding this way; this is genuinely new plumbing. No `.id()` on the list (rail).
- [ ] **4.5 `FeedView.swift`**: add `@Environment(AppRouter.self) private var router`; add
  ```swift
  .onAppear { consumePendingAddSource() }
  .onChange(of: router.pendingAddSource) { _, _ in consumePendingAddSource() }
  ```
  and
  ```swift
  private func consumePendingAddSource() {
      guard let tile = router.consumeAddSource() else { return }
      openSheet(tile)
  }
  ```
  (reuses the existing private `openSheet(_:)` byte-for-byte).
- [ ] **4.6 `ContentView.swift`**: add `@Environment(AppRouter.self) private var router`; add
  ```swift
  .onChange(of: router.pendingTab) { _, newTab in
      guard let newTab else { return }
      withAnimation(.spring(duration: 0.25)) { selectedTab = newTab }
      router.pendingTab = nil
  }
  ```
- [ ] **4.7 `CicadaApp.swift`**: `@State private var appRouter = AppRouter()`; `.environment(appRouter)` on both the `WindowGroup` content and `SettingsScene()`.
- [ ] **4.8 Build + test.** `swift build 2>&1 | tail -5`; `swift test 2>&1 | tail -20` — 0 failures.
- [ ] **4.9 Commit.** Stage: `Sources/CicadaApp/Models/IntegrationCategory.swift Sources/CicadaApp/Support/AppRouter.swift Sources/CicadaApp/Views/Settings/IntegrationsView.swift Sources/CicadaApp/Views/Feed/FeedView.swift Sources/CicadaApp/ContentView.swift Sources/CicadaApp/CicadaApp.swift Tests/CicadaAppTests/IntegrationsViewTests.swift Tests/CicadaAppTests/AppRouterTests.swift`. Commit: `feat(G126): Settings → Integrations page over the existing channel registry`.

---

## Task 5 — Docs

**Files:** `CLAUDE.md`, `docs/goals/memory-evolution.md`, `docs/goals/TODO.md`, `docs/goals/working-method.md`.

### Steps

- [ ] **5.1** `CLAUDE.md` → Companion App → Navigation: replace "Setup lives in a native `Settings{}` scene (⌘,)" with a line describing the five-section sidebar (General · Sleep · Integrations · Agents · Plans & keys), the Sleep section's engine picker (one sentence, citing G122, noting ruling 4 is displayed not hidden), and the Integrations rule ("standing connections live here; the Feed's `+` stays the place for a one-shot import — G126").
- [ ] **5.2** `docs/goals/memory-evolution.md`: G122 row status `🔲` → `✅`; append to its cell "what stays open: Codex as an engine (`codex exec`) is G49's engine-ladder half; a new adapter is its own row." G126 row status `🔲` → `🛠️` (page shipped, adapters open); append "the page ships over the existing registry; Strava/Todoist-Reminders/YouTube-subscriptions/Garmin-Apple-Health remain their own future rows."
- [ ] **5.3** `docs/goals/TODO.md`: update the "Pick up here" / handoff header to note Track C (G122 + G126 page) shipped, and which PR/commit range. Follow the privacy rule (no personal names/paths).
- [ ] **5.4** `docs/goals/working-method.md` §3 (the paused queue): mark G122/G126-page as done, leaving G117 (onboarding, reuses this track's EngineCard + Integrations page per the spec) and the adapter rows in place, unreordered.
- [ ] **5.5 Commit.** Stage exactly the four files above. Commit: `docs(G122/G126): settings redesign shipped — engine picker, Integrations page`.

---

## Not in scope

- Any new connector/adapter (G94, G111, G119, G13, G120 rows) — the Integrations page is a frame over the *existing* registry only.
- Codex as a selectable Sleep engine (the `codex exec` half of **G49**'s engine ladder, still open) — its candidate row stays permanently `available: false`.
- G117's first-run onboarding sheet — it will reuse `EngineCard` and `IntegrationsView` later; nothing here builds onboarding itself.
- Any change to `channel_registry.py`, `connectors/`, or the Feed's `+` catalog's own contents — Integrations only *reads* `GET /sources/channels` / `GET /sources/overview` and *routes into* the existing Feed sheet.
- Prices, token counts, or cost estimates anywhere in the new UI (G124 stands).
- A "reset engine prefs to default" affordance — not asked for; the picker always has a definite mode to show.
- Any ETag change — `/sleep/engine` is deliberately unETag'd, matching `/sleep/schedule`'s own precedent (a Settings-shaped, single-owner GET/PUT pair, not a Store-synced domain).

## Verification (run at the end, orchestrator-facing)

```
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/settings
api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider
# expect: 0 failures (2014+ passed); if the single order-dependent decay test
# is the only red, re-run it alone and report both results.

cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/settings/app/CicadaApp
swift build 2>&1 | tail -5
swift test 2>&1 | tail -20
# expect: build succeeds; 0 test failures.

cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/settings
git log --oneline dev..feat/settings-redesign
git diff --stat dev...feat/settings-redesign
```
Read the diff once, end to end, before calling this done — the two-lens final review (correctness + simplification) that `working-method.md` describes.
