# Companion Gamification + Plug-and-Play Install — v2 Design Spec

Axis owner deliverable for the Cicada v2 revamp (`feat/v2-revamp`).

Scope of this axis:

- **(a)** Menu-bar pixel bookworm tamagotchi — a code-defined sprite system driven by backend state.
- **(b)** Wiring the tamagotchi to live app/backend state (fixes the known gap: `MenuBarManager.updateStatus` is never called).
- **(c)** Plug-and-play install — one idempotent `install.sh`, a `Makefile` with `install`/`uninstall`/`doctor`, launchd plists.
- **(d)** Local embedding fallback — `CICADA_EMBEDDING_MODE=openai|local` threaded `config.py` → `LeannIndexer`.
- **(e)** Claude-skill distribution sketch (`SKILL.md`) so an agent can drive the memory dir + MCP tools.

This spec is decisive — one approach per problem. It is sized for a single developer to land in days.

---

## 0. Cross-axis contracts this design depends on

These come from sibling axes. This spec assumes them and degrades gracefully if absent.

1. **`GET /status` aggregate endpoint** (owned by the *unified-inbox* axis). The tamagotchi polls this. Required shape (camelCase on the wire, the project uses `CamelModel` with `alias_generator=to_camel`):

   ```jsonc
   // GET /status  ->  200
   {
     "sleep": {                       // mirror of /sleep/status, may be inlined
       "status": "idle",              // "idle" | "running"
       "stage": 0,                    // 0..5
       "totalStages": 5,
       "cycleId": "sleep_2026-06-12_030000",
       "error": null
     },
     "inbox": {
       "total": 7,                    // unified inbox pending count (nudges+clarifications merged)
       "byKind": { "decay": 4, "conflict": 1, "clarification": 2 }
     },
     "episodes": {
       "unprocessed": 3,
       "lastIngestedAt": "2026-06-11T22:04:11Z"   // ISO8601, null if none
     },
     "lastSleepAt": "2026-06-12T03:01:55Z",        // null if never
     "nextSleepAt": "2026-06-13T03:00:00Z"         // null if schedule disabled
   }
   ```

   **Fallback if `/status` is not yet merged:** the tamagotchi composes the same struct client-side from `GET /sleep/status`, `GET /sleep/episodes`, `GET /sleep/schedule`, and (legacy) `GET /nudges` + `GET /clarifications`. This axis ships that fallback so it is not blocked on the inbox axis. A single `StatusService` actor abstracts the source; flipping to `/status` later is a one-line change.

2. **Unified inbox count.** If the inbox axis lands, `inbox.total` is the single badge number. Until then the fallback sums the two legacy directories. Either way the tamagotchi only reads a single integer + per-kind map.

This axis does **not** modify inbox storage, hub generation, or entity-page schema. It only consumes their counts.

---

## 1. Menu-bar pixel bookworm tamagotchi

### 1.1 Design rationale (one approach, justified)

**Encode each sprite as a 2D bitmap grid in Swift code** (arrays of strings, `#` = lit pixel, space = transparent), rendered via `CGContext` into an `NSImage` marked `isTemplate = true`. macOS then tints the white pixels to match the menu-bar appearance (works in dark *and* light bars, and respects the "reduce transparency"/accent settings). This beats shipping a PNG sprite sheet because:

- The canonical mascot (`app/assets/book_worm.png`) is already a 1-bit white-on-black pixel worm — it maps directly to a `#`/space grid with zero asset-pipeline work, and the PNG is currently **not bundled** into the SwiftPM target anyway (`Package.swift` only copies `Resources/`).
- Template `NSImage` tinting solves the dark/light menu-bar problem for free; a baked PNG would need two color variants.
- Animation = swapping grids on a `Timer`, no sprite-sheet slicing, no `Resources` additions, no `Package.swift` change.
- It is trivially testable and diffable in code review (the worm is literally readable in the source).

The menu-bar icon target is a **16×16 point** template image rendered at 2× (32×32 px backing) for Retina crispness. The mascot grid is authored at **16×16 cells**.

### 1.2 Sprite source-of-truth: the canonical worm

The base "awake idle" frame is a 16×16 transcription of `book_worm.png`: a round-glasses head (two circular lenses joined by a bridge), a smiling mouth, and a segmented body curling down-left. All other states are deltas on this base (eyes, mouth, body, plus overlays like `zZz` or a badge). The grids live in `BookwormSprites.swift` (see 1.5). Authoring rule: keep the **head + glasses silhouette stable across all states** so the character reads as the same worm; only animate eyes, mouth, body wiggle, and overlays.

### 1.3 State machine

`CicadaStatus` is replaced by a richer `BookwormState` enum. Each state has: a display title, a one-line description, an animation (ordered list of frame grids), a frame interval, and optional overlay metadata (badge count, sleep-stage dots).

| State | Trigger | Visual | Animation |
|-------|---------|--------|-----------|
| `awake` | default; inbox empty-ish, episodes recent | idle worm, glasses, slight smile | mostly static; **blink** every ~4–6 s (eyes close for 1 frame) |
| `sleeping(stage:Int)` | `sleep.status == "running"` | closed/`-` eyes, floating `zZz` glyph above head, **1–5 tiny progress dots** under the worm showing the current sleep stage | `zZz` rises/fades over 3 frames; dots fill as `stage` advances |
| `digesting` | first ~6 s after a cycle finishes (running→idle, no error) | open eyes, **chewing** mouth | mouth grid cycles open/closed 3× then reverts to `awake` |
| `happy` | inbox `total == 0` (and not sleeping/digesting) | big smile, occasional sparkle pixel | 2-frame sparkle blink every ~3 s |
| `curious(count:Int)` | inbox `total > 0` | raised "eyebrow" pixels + **badge count** drawn as a small numeric overlay in the corner | subtle head-tilt 2-frame loop |
| `hungry` | no episode ingested in **48 h** (`episodes.lastIngestedAt` older than 48h, or null) | droopy mouth, half-lidded eyes | slow 2-frame sway; no sparkle |

Priority when multiple conditions hold (highest wins): `sleeping` > `digesting` > `hungry` > `curious` > `happy` > `awake`. (Sleeping always dominates; a running cycle is the most important thing to show. `hungry` outranks `curious`/`happy` because "feed me" is the actionable nudge.)

The badge count for `curious` is `min(inbox.total, 99)` rendered as up-to-2-digit pixels; `99+` collapses to `99`.

### 1.4 State derivation (pure function, unit-testable)

A free function maps a status snapshot → `BookwormState`. Keep it pure so it can be tested without the menu bar:

```swift
// StatusSnapshot is the decoded /status struct (or the composed fallback).
func deriveBookwormState(
    _ s: StatusSnapshot,
    justFinishedAt: Date?,   // set when a cycle transitions running->idle
    now: Date = .now
) -> BookwormState {
    if s.sleep.status == "running" {
        return .sleeping(stage: max(1, min(5, s.sleep.stage)))
    }
    if let f = justFinishedAt, now.timeIntervalSince(f) < 6 {
        return .digesting
    }
    let stale = s.episodes.lastIngestedAt.map { now.timeIntervalSince($0) > 48*3600 } ?? true
    if stale { return .hungry }
    if s.inbox.total > 0 { return .curious(count: s.inbox.total) }
    return .happy   // inbox empty, fed, idle
}
```

`awake` is the cold-start / unknown state (used before the first poll resolves, and when `/status` is unreachable).

### 1.5 New files

```
app/CicadaApp/Sources/CicadaApp/MenuBar/BookwormState.swift      (create)
app/CicadaApp/Sources/CicadaApp/MenuBar/BookwormSprites.swift    (create)
app/CicadaApp/Sources/CicadaApp/MenuBar/BookwormRenderer.swift   (create)
app/CicadaApp/Sources/CicadaApp/MenuBar/MenuBarManager.swift     (MOVE + rewrite from Sources/CicadaApp/MenuBarManager.swift)
app/CicadaApp/Sources/CicadaApp/Services/StatusService.swift     (create)
```

**`BookwormState.swift`** — the enum above plus `title`/`description` computed properties (reuse the existing copy from `CicadaStatus`).

**`BookwormSprites.swift`** — the grids. Shape:

```swift
enum BookwormSprites {
    // 16 rows x 16 cols. '#' = lit pixel, ' ' = transparent.
    // Base frame transcribed from app/assets/book_worm.png:
    // round twin-lens glasses, smile, segmented body curling down-left.
    static let awakeOpen: [String] = [
        "                ",
        "    ####  ####   ",
        "   #....##....#  ",   // '.' authoring marker for lens interior; treated as transparent (eye white)
        "   #.##.##.##.#  ",   //  glasses frames + pupils
        "   #.##.##.##.#  ",
        "   #....##....#  ",
        "    ####  ####   ",
        "     # #  # #    ",   // smile corners under bridge
        "      ######     ",   // mouth (smile)
        "       ####      ",
        "      ##  ##     ",   // body segment 1
        "    ##      #    ",
        "   #    ####     ",   // curling tail segments
        "  #  ###         ",
        "  ####           ",
        "                 ",
    ]
    static let awakeBlink: [String]      // same head, eyes drawn as a single '-' row
    static let sleepEyes: [String]       // closed eyes (two '-' segments), neutral mouth
    static let zzzFrame1/2/3: [String]   // overlay-only grids: a 'z' climbing up-right, used on top of sleepEyes
    static let chew1/chew2: [String]     // mouth open vs closed for digesting
    static let happy: [String]           // wide smile
    static let sparkle: [String]         // happy + one extra lit pixel top-right
    static let curiousTilt1/2: [String]  // raised brow + slight tilt
    static let hungryDroop: [String]     // half-lidded eyes, downturned mouth

    // Animation = ordered frames + interval.
    static func frames(for state: BookwormState) -> (frames: [[String]], interval: TimeInterval)
    // Digit glyphs for the curious badge (3x5 mini-font), drawn bottom-right.
    static let digits: [Character: [String]]
    // Stage dots: returns a 16x16 overlay grid lighting `stage` of 5 dots on the bottom row.
    static func stageDots(_ stage: Int) -> [String]
}
```

The exact pixel transcription of every frame is left to implementation against `book_worm.png`; the grid above is the canonical reference for the head silhouette and proportions. **Constraint:** glasses + head silhouette identical across `awakeOpen`, `happy`, `curious`, `hungry`, `digesting` so the character is recognizable; only eyes/mouth/body/overlay differ.

**`BookwormRenderer.swift`** — turns a grid (+ optional overlays) into a template `NSImage`:

```swift
enum BookwormRenderer {
    /// Render one frame (16x16 grid) into a template NSImage sized `pointSize`x`pointSize`.
    /// Overlays (badge digits, stage dots, zZz) are merged onto the grid before raster.
    static func image(
        grid: [String],
        overlays: [[String]] = [],
        pointSize: CGFloat = 16
    ) -> NSImage
}
```

Implementation notes:
- Build an `NSImage(size: NSSize(width: pointSize, height: pointSize))`, `lockFocus()`, fill each `#`/digit/dot cell as a `pointSize/16`-sized black rect (color is irrelevant — template mode tints it).
- `image.isTemplate = true` so the menu bar tints it correctly for dark + light.
- Merge overlays by OR-ing lit cells onto the base grid before rasterizing (badge digits occupy bottom-right 3×5, stage dots bottom row, `zZz` top-right).
- Cache rendered `NSImage`s in a dictionary keyed by `(stateCaseName, frameIndex, badgeCount, stage)` so the timer is cheap.

### 1.6 Rewritten `MenuBarManager`

`MenuBarManager` becomes the controller: owns the `NSStatusItem`, a frame `Timer`, the current `BookwormState`, and the dropdown menu. Key surface:

```swift
@Observable
final class MenuBarManager: NSObject {
    private(set) var state: BookwormState = .awake
    private var statusItem: NSStatusItem?
    private var frameTimer: Timer?
    private var frameIndex = 0
    private var currentSnapshot: StatusSnapshot?

    // Closures injected by the App for the quick actions.
    private var onOpenApp: (() -> Void)?
    private var onRunSleep: (() async -> Void)?
    private var onSaveClipboardURL: (() async -> Void)?

    func setup(onOpenApp: @escaping () -> Void,
               onRunSleep: @escaping () async -> Void,
               onSaveClipboardURL: @escaping () async -> Void)

    /// Called by StatusService every 30s and immediately after actions.
    func apply(snapshot: StatusSnapshot, justFinishedAt: Date?)

    private func transition(to newState: BookwormState)  // resets frameIndex + restarts frameTimer
    private func tick()                                  // advances frameIndex, re-renders icon
    private func rebuildMenu()                            // dropdown reflects current snapshot
}
```

- `apply(snapshot:justFinishedAt:)` computes `deriveBookwormState(...)`; if the case changed, calls `transition`; always `rebuildMenu()` (counts/times may have moved without a state change).
- `transition` invalidates the old `frameTimer`, resets `frameIndex`, looks up `BookwormSprites.frames(for:)`, renders frame 0, and starts a `Timer` at the state's interval that calls `tick()`.
- `tick()` advances `frameIndex` mod frame count, re-renders (overlays computed from `currentSnapshot`), assigns to `statusItem.button.image`.
- The frame timer is **paused** (invalidated) when the dropdown menu is open is not required — keep it simple; a 0.25–0.5 s tick is negligible.

### 1.7 Dropdown menu (driven by snapshot)

`rebuildMenu()` produces:

```
[ ◐ Sleeping — stage 3/5         ]   (disabled status header: state.title + dynamic detail)
---------------------------------
  Inbox: 7 items                     (disabled; "Inbox: empty" when 0)
  Last sleep: 6h ago                 (relative from lastSleepAt; "never" if null)
  Next sleep: tonight 3:00 AM        (from nextSleepAt; "not scheduled" if null)
---------------------------------
  Run sleep cycle now        ⌘R      (calls onRunSleep; disabled while running)
  Save clipboard URL         ⌘S      (calls onSaveClipboardURL; see 3.x media bridge)
  Open Cicada                ⌘O
---------------------------------
  Quit Cicada                ⌘Q
```

Detail strings:
- `sleeping`: `"stage \(stage)/5"`.
- `digesting`: `"chewing on new memories…"`.
- `curious(n)`: `"\(n) item\(n==1 ? "" : "s") waiting"`.
- `hungry`: `"no episodes in 48h"`.
- `happy`: `"inbox clear"`.

"Run sleep cycle now" is `isEnabled = (sleep.status != "running")`. "Save clipboard URL" reads `NSPasteboard.general.string(forType: .string)`, validates it looks like a URL, and posts it to the sources/media ingest endpoint **if that endpoint exists** (owned by the media axis: `POST /sources/ingest` or `POST /media/save`); if the endpoint 404s, the action shows a transient "Cicada: media ingest not available" via the menu (no crash). This keeps the quick action useful the moment the media axis lands without coupling to it.

### 1.8 `StatusService` (polling)

```swift
actor StatusService {
    static let shared = StatusService()
    func fetch() async -> StatusSnapshot?   // tries GET /status, falls back to composed snapshot
}
```

`StatusSnapshot` is a `Codable` struct matching §0. The composed fallback issues the legacy calls concurrently (`async let`) and assembles the same struct. `lastIngestedAt` in fallback = max `timestamp` over episodes from `GET /sleep/episodes`; `nextSleepAt` = computed from `GET /sleep/schedule` (next occurrence of hour:minute, or null if disabled); `lastSleepAt` = first entry of `GET /sleep/history` (already filtered to "Sleep cycle" commits), or null.

---

## 2. Wiring — fix the dead `updateStatus` path

Today `MenuBarManager.updateStatus` exists but **nothing calls it**; the icon is permanently `eye`. The fix has three legs.

### 2.1 30-second poll loop, owned by the App

In `CicadaApp.swift`, add a single long-lived poll task started in `.onAppear` (after `menuBarManager.setup(...)`). It tracks the running→idle transition to set `justFinishedAt` (drives `digesting`):

```swift
.onAppear {
    backend.start()
    menuBarManager.setup(
        onOpenApp: { /* activate + key window (existing logic) */ },
        onRunSleep: { await sleepVM.triggerManually(); await refreshMenuBar() },
        onSaveClipboardURL: { await menuBarManager.saveClipboardURL() }
    )
    sleepVM.onCycleCompleted = { [graphVM] in await graphVM.loadGraph() }

    // NEW: drive the tamagotchi.
    menuPollTask = Task { @MainActor in
        var wasRunning = false
        var justFinishedAt: Date? = nil
        while !Task.isCancelled {
            if let snap = await StatusService.shared.fetch() {
                let nowRunning = snap.sleep.status == "running"
                if wasRunning && !nowRunning { justFinishedAt = Date() }   // cycle just ended
                wasRunning = nowRunning
                menuBarManager.apply(snapshot: snap, justFinishedAt: justFinishedAt)
            }
            try? await Task.sleep(for: .seconds(30))
        }
    }
}
```

`menuPollTask` is a `@State private var menuPollTask: Task<Void, Never>?`. Cancel it in `.onDisappear`.

### 2.2 Immediate refresh after actions

Anything that mutates inbox/sleep/episode state calls a shared `refreshMenuBar()` that does one immediate `StatusService.fetch()` + `apply`, instead of waiting up to 30 s:

- After `sleepVM.triggerManually()` (so the icon flips to `sleeping` instantly).
- After resolving an inbox item / nudge / clarification (badge drops immediately).
- After a successful conversation/media upload (episode count + possible `hungry`→`awake`).

Implementation: add `func refreshMenuBar() async` to the App (or a small `@Observable AppCoordinator`) that calls `StatusService.fetch()` and `menuBarManager.apply(...)`. Wire it into `UploadOverlay`'s completion, the inbox/nudge/clarification resolve handlers, and `triggerManually`.

### 2.3 Observe `SleepViewModel` directly (belt-and-suspenders)

The 1-second `SleepViewModel.startPolling()` loop already knows about running/idle precisely. Add a hook so the menu bar reacts within ~1 s during an active cycle (the 30 s poll is too coarse to animate stage dots smoothly):

- Add `var onStatusChanged: (@MainActor (SleepStatusResponse) -> Void)?` to `SleepViewModel`.
- In `startPolling()`'s loop, after `self.status = next`, call `self.onStatusChanged?(next)`.
- In the App, wire `sleepVM.onStatusChanged = { next in menuBarManager.applySleep(next) }`.
- `MenuBarManager.applySleep(_:)` patches only the sleep portion of `currentSnapshot` and re-derives state — this is what makes the 1–5 stage dots advance live without waiting for the 30 s poll.

Net effect: idle state refreshes every 30 s (cheap); during a running cycle the 1 s sleep poll feeds stage progress straight into the dots. The two never conflict because `applySleep` only touches the sleep sub-struct.

### 2.4 Files touched for wiring

```
app/CicadaApp/Sources/CicadaApp/CicadaApp.swift                 (modify: poll task, action closures, onStatusChanged)
app/CicadaApp/Sources/CicadaApp/ViewModels/SleepViewModel.swift (modify: add onStatusChanged hook in startPolling)
app/CicadaApp/Sources/CicadaApp/Views/Common/UploadOverlay.swift(modify: call refreshMenuBar on success)
```

The legacy `CicadaStatus` enum is deleted; `AppTab` `.nudges`/`.clarifications` are out of this axis's scope (the inbox axis collapses them) but the menu-bar badge already reads the unified `inbox.total`, so the menu is correct regardless of which inbox UI ships.

---

## 3. Plug-and-play install

Two install surfaces: a single idempotent **`install.sh`** (the real worker) and a thin **`Makefile`** wrapper with `install` / `uninstall` / `doctor`. `BackendProcess` stays the *dev* path (spawn uvicorn as a child); launchd is the *install* path (backend runs as a `LaunchAgent` independent of the app).

### 3.1 Target install layout

```
~/cicada/
  memory/                       (git repo; created if absent)
    episodes/ entities/ nudges/ clarifications/ inbox/ leann/ sources/
    graph_edges.yaml  sleep_schedule.yaml
  app/  api/  mcp/               (copied or symlinked from the repo on install)
  .env                          (single source; symlinked from api/.env)
~/Library/LaunchAgents/
  ai.cicada.backend.plist       (RunAtLoad + KeepAlive uvicorn)
  ai.cicada.sleep.plist         (optional nightly StartCalendarInterval -> POST /sleep/trigger)
~/.claude/  (or client config)  cicada-bookworm MCP entry
```

Decision: install **copies the repo's `api/`, `mcp/`, and built app into `~/cicada/`** and points launchd at `~/cicada/api/.venv/bin/uvicorn`. This makes the install self-contained and survives the developer moving/deleting the source checkout. For development, `install.sh --dev` instead symlinks `~/cicada/api` → the repo and uses the repo `memory/`.

### 3.2 `install.sh` — idempotent, prompt-or-env driven

`scripts/install.sh` (create). Idempotency rule: every step checks current state and is safe to re-run. Flags: `--dev` (symlink instead of copy, use repo memory), `--no-launchd`, `--no-mcp`, `--nightly HH:MM` (enable the nightly timer), `--embedding-mode openai|local`, `--non-interactive` (read everything from env, never prompt).

Steps (each numbered, each idempotent):

1. **Preflight.** Verify macOS, `git`, and `uv` are present (`command -v uv` — if missing, print the one-line `curl … | sh` install hint and exit 2). Verify Python 3.12 reachable.
2. **Create memory tree.** `mkdir -p ~/cicada/memory/{episodes,entities,nudges,clarifications,inbox,sources,leann}`. (Including `inbox/` and `sources/` so the inbox + media axes have their dirs even on a fresh box.) Skip silently if present.
3. **git init memory.** If `~/cicada/memory/.git` absent: `git init`, write a minimal `.gitignore` (ignore `leann/` blobs if desired), `git add -A && git commit -m "Initial Cicada memory"` (only if there is something to commit). Re-run = no-op.
4. **Place code.** Copy (or `--dev` symlink) `api/`, `mcp/` into `~/cicada/`. `rsync -a --delete` for copy mode so re-runs update in place.
5. **`uv sync`.** `cd ~/cicada/api && uv sync` (creates `.venv`). Re-run is naturally idempotent.
6. **Write `.env`.** If `~/cicada/api/.env` exists, **do not clobber** — only fill missing keys. Otherwise create from prompts (or env when `--non-interactive`):
   - `CICADA_MEMORY_PATH` → `~/cicada/memory` (auto).
   - `CICADA_EMBEDDING_MODE` → from `--embedding-mode`, default `openai` if an OpenAI key is provided, else **auto-fall to `local`** (see §4) and print a notice.
   - `OPENAI_API_KEY` (prompt; **optional** — empty is allowed when embedding-mode=local and the sleep model is a non-OpenAI provider).
   - `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` (prompt, optional).
   - `CICADA_LITELLM_MODEL`, `CICADA_LITELLM_DISAMBIGUATION_MODEL` (defaults from `.env.example`).
   - Symlink `~/cicada/.env` → `api/.env` for convenience.
   - Never echo secrets to stdout; write with `umask 077`.
7. **Register MCP server.** Prefer `claude mcp add` (the supported CLI):
   ```sh
   claude mcp add cicada-bookworm \
     --scope user \
     --env CICADA_MEMORY_PATH="$HOME/cicada/memory" \
     -- "$HOME/cicada/api/.venv/bin/python" "$HOME/cicada/mcp/server.py"
   ```
   If `claude` is not on PATH (or `--no-mcp`), fall back to **manual JSON merge**: read the user's MCP config (`~/.claude/mcp_servers.json` or the path in `$CICADA_MCP_CONFIG`), merge a `cicada-bookworm` entry (don't overwrite an existing one unless `--force`), and write it back with a backup `.bak`. The merged entry uses the venv python + absolute paths (no `/path/to/cicada` placeholders — this replaces the broken template in `mcp/mcp_config.json`).
8. **Install backend launchd plist** (unless `--no-launchd`). Render `ai.cicada.backend.plist` (template in `scripts/launchd/`) into `~/Library/LaunchAgents/`, substituting absolute venv/uvicorn paths and `CICADA_MEMORY_PATH`. `RunAtLoad=true`, `KeepAlive=true`, logs to `~/cicada/logs/backend.{out,err}.log`. Then `launchctl bootout gui/$UID/ai.cicada.backend 2>/dev/null; launchctl bootstrap gui/$UID <plist>` (bootout-then-bootstrap = idempotent reload). Wait up to ~10 s for `GET /healthz` to 200.
9. **Optional nightly sleep timer** (`--nightly HH:MM`). Render `ai.cicada.sleep.plist` with `StartCalendarInterval` at HH:MM; its program is a tiny `curl -fsS -X POST http://127.0.0.1:8000/sleep/trigger` wrapper (`scripts/run-sleep.sh`). Bootstrap it. If `--nightly` omitted, skip (the in-process APScheduler remains available via the app's Sleep dashboard). **Decision:** launchd nightly is opt-in; the in-process scheduler stays the default so we don't double-fire. The two are mutually exclusive by docs (installer prints a warning if both the plist and `sleep_schedule.yaml.enabled` are on).
10. **Smoke test.** Call the same checks as `doctor` (§3.4) and print a green/red summary. Exit non-zero if backend didn't come up.

`install.sh` prints a final "what happened" block (paths created, MCP registered y/n, launchd loaded y/n, embedding mode).

### 3.3 New backend route required: `GET /healthz`

Add a trivial liveness endpoint so the installer/doctor can probe without auth:

```
GET /healthz -> 200 {"status":"ok","memoryPath":"…","embeddingMode":"local","entityCount":1882}
```

`api/routers/health.py` (create), registered in `api/main.py`. `embeddingMode` reflects the resolved `settings.embedding_mode` (§4) so doctor can confirm the offline path is actually active.

### 3.4 `Makefile` targets

Append to the existing `Makefile` (it currently only has benchmark targets). Add to `.PHONY`: `install uninstall doctor backend-logs`.

```make
install:                      ## one-command plug-and-play install
	bash scripts/install.sh $(INSTALL_FLAGS)

uninstall:                    ## remove launchd agents + MCP entry (keeps ~/cicada/memory)
	bash scripts/uninstall.sh $(UNINSTALL_FLAGS)

doctor:                       ## health checks: backend, LEANN, MCP, git
	bash scripts/doctor.sh

backend-logs:
	tail -n 100 -f ~/cicada/logs/backend.err.log
```

`INSTALL_FLAGS`/`UNINSTALL_FLAGS` pass through (e.g. `make install INSTALL_FLAGS="--dev --no-launchd"`).

### 3.5 `scripts/doctor.sh` — health checks

Each check prints `[ok]`/`[FAIL]` + a one-line remedy; exit code = number of failures.

1. **Backend up** — `curl -fsS http://127.0.0.1:8000/healthz`. FAIL remedy: "run `make backend-logs` / `launchctl bootstrap`".
2. **LEANN present** — `~/cicada/memory/leann/entities.meta.json` and `episodes.meta.json` exist (the `.meta.json` sidecar is the real "index built" marker, per `_search` in `leann_indexer.py`). Remedy: "run a sleep cycle or `make rebuild-episodes`".
3. **MCP registered** — `claude mcp list 2>/dev/null | grep -q cicada-bookworm`, OR the manual JSON contains the entry. Remedy: re-run install `--no-launchd` (MCP-only) or manual snippet path.
4. **git ok** — `git -C ~/cicada/memory rev-parse --git-dir` succeeds and `git status` is clean-ish (warn, don't fail, on dirty tree). Remedy: "memory dir is not a git repo; re-run install".
5. **Embedding mode sane** — read `embeddingMode` from `/healthz`; if `openai` but no `OPENAI_API_KEY` in env/.env, FAIL with "set OPENAI_API_KEY or `--embedding-mode local`".
6. **Python/venv** — `~/cicada/api/.venv/bin/python -c "import leann, litellm"` succeeds.

### 3.6 `scripts/uninstall.sh`

Idempotent reverse: `launchctl bootout` both agents (ignore errors), delete the two plists, remove the `cicada-bookworm` MCP entry (`claude mcp remove cicada-bookworm` or JSON un-merge with `.bak` restore). **Never** delete `~/cicada/memory` (data-loss guard — print its path and "left intact"). `--purge` flag (explicit) additionally removes `~/cicada/{api,mcp,app,logs}` but still leaves `memory/`.

### 3.7 launchd plist templates

`scripts/launchd/ai.cicada.backend.plist` (create, with `__PLACEHOLDER__` tokens the installer substitutes):

```xml
<!-- key fields -->
<key>Label</key>            <string>ai.cicada.backend</string>
<key>ProgramArguments</key> <array>
  <string>__VENV__/bin/uvicorn</string>
  <string>api.main:app</string>
  <string>--host</string><string>127.0.0.1</string>
  <string>--port</string><string>8000</string>
</array>
<key>WorkingDirectory</key> <string>__CICADA_HOME__</string>   <!-- so `api.main:app` imports -->
<key>EnvironmentVariables</key> <dict>
  <key>CICADA_MEMORY_PATH</key><string>__MEMORY__</string>
  <key>PYTHONPATH</key>        <string>__CICADA_HOME__</string>
</dict>
<key>RunAtLoad</key>  <true/>
<key>KeepAlive</key>  <true/>
<key>StandardOutPath</key>  <string>__LOGS__/backend.out.log</string>
<key>StandardErrorPath</key><string>__LOGS__/backend.err.log</string>
```

The backend loads `OPENAI_API_KEY` etc. from `api/.env` via `pydantic-settings` (`env_file=".env"`), so secrets need not go in the plist — keeping them out of `launchctl print`. `WorkingDirectory` must be `~/cicada` (the dir containing `api/`) for `api.main:app` to import, mirroring `BackendProcess.currentDirectoryURL`.

`scripts/launchd/ai.cicada.sleep.plist` — same skeleton, `Program` = `__CICADA_HOME__/scripts/run-sleep.sh`, `StartCalendarInterval` hour/minute substituted, `RunAtLoad=false`, `KeepAlive=false`.

### 3.8 `BackendProcess` stays, with one guard

`BackendProcess.start()` already skips spawning if port 8000 is in use (its `isPortInUse` check). With the launchd agent running, the app will correctly detect the port is taken and not double-spawn — **no code change needed**, the existing guard already makes dev (`swift run` → child uvicorn) and install (launchd → app sees port busy) coexist. Add only a comment documenting that launchd is the production owner. Optionally add a `~/cicada/logs/` `mkdir` in `install.sh` (BackendProcess already nulls its stdio).

### 3.9 New install files summary

```
scripts/install.sh                       (create)
scripts/uninstall.sh                     (create)
scripts/doctor.sh                        (create)
scripts/run-sleep.sh                     (create: curl POST /sleep/trigger)
scripts/launchd/ai.cicada.backend.plist  (create: template)
scripts/launchd/ai.cicada.sleep.plist    (create: template)
mcp/mcp_config.json                      (modify: keep as documented manual-fallback example; note it's auto-generated by install.sh)
Makefile                                 (modify: add install/uninstall/doctor/backend-logs)
api/routers/health.py                    (create: GET /healthz)
api/main.py                              (modify: include health router)
```

---

## 4. Local embedding fallback (`CICADA_EMBEDDING_MODE`)

Goal: install works with **no OpenAI key**. Today `leann_indexer.py` hardcodes `EMBEDDING_MODE="openai"` / `EMBEDDING_MODEL="text-embedding-3-small"` as module constants — `OPENAI_API_KEY` is a hard requirement.

### 4.1 Config surface (`api/config.py`)

Add to `Settings` (env prefix `CICADA_` already in place):

```python
# Embedding backend for the LEANN indexes.
#   "openai" -> text-embedding-3-small via OpenAI (needs OPENAI_API_KEY)
#   "local"  -> sentence-transformers on-device (no API key, ~90MB model download)
embedding_mode: str = "openai"            # CICADA_EMBEDDING_MODE
embedding_model_openai: str = "text-embedding-3-small"   # CICADA_EMBEDDING_MODEL_OPENAI
embedding_model_local: str = "sentence-transformers/all-MiniLM-L6-v2"  # CICADA_EMBEDDING_MODEL_LOCAL
```

**Auto-degrade rule (in `get_settings`/a validator):** if `embedding_mode == "openai"` but `OPENAI_API_KEY` is unset/empty, log a warning and switch the effective mode to `"local"`. This makes a key-less install *work* instead of silently producing a stale index (current behavior: cycle finishes with an `index_warning`, search goes dark). The resolved mode is surfaced in `/healthz`.

### 4.2 Thread config into `LeannIndexer`

`leann_indexer.py` changes:

- Delete the module constants `EMBEDDING_MODE` / `EMBEDDING_MODEL`; replace with instance fields set in `__init__` from `Settings` (or explicit args, so benchmarks can override without env):

  ```python
  def __init__(self, memory_path: Path, *,
               embedding_mode: str | None = None,
               embedding_model: str | None = None):
      settings = get_settings()
      self.embedding_mode = embedding_mode or settings.resolved_embedding_mode  # applies auto-degrade
      self.embedding_model = embedding_model or (
          settings.embedding_model_local if self.embedding_mode != "openai"
          else settings.embedding_model_openai
      )
  ```

- `_make_builder()` uses `self.embedding_mode` / `self.embedding_model`. For `local`, LEANN's builder accepts `embedding_mode="sentence-transformers"` (or `"local"`) with the model name; pass the resolved values through (`backend_name="hnsw"` unchanged).
- `_safe_build()`: the special OpenAI batching path (`_build_with_batched_embeddings`) is **only** for `embedding_mode == "openai"` (it calls `compute_embeddings_openai`). The existing `else: builder.build_index(str(target))` branch already handles non-OpenAI — local mode flows through it. No batching needed locally (no 300k-token request cap; sentence-transformers runs in-process).
- Every other call site that constructs `LeannIndexer(memory_path)` keeps working (defaults pull from `Settings`). Benchmarks that want a fixed mode pass it explicitly.

The dimension change (OpenAI 1536 vs MiniLM 384) is transparent: LEANN infers dimensions from the embeddings, and indexes are mode-specific directories rebuilt by the sleep cycle. **Migration note:** an index built under one mode must not be searched under another (dimension mismatch). The installer/`doctor` records the mode; switching modes requires a rebuild (`make rebuild-episodes` + a sleep cycle). Document this loudly.

### 4.3 Dependency weight — documented honestly

`local` mode needs `sentence-transformers` (pulls `torch`). This is **heavy**: torch alone is ~200MB+ (CPU wheel), the MiniLM model ~90MB on first use. To avoid forcing this on every user:

- Add an **optional dependency group** in `api/pyproject.toml`:
  ```toml
  [project.optional-dependencies]
  local-embeddings = ["sentence-transformers>=2.2"]
  ```
  (`sentence-transformers` already resolves transitively via `leann` in `uv.lock`, so this mostly pins/exposes it rather than adding net-new weight — verify during impl.)
- `install.sh`: when resolved mode is `local`, run `uv sync --extra local-embeddings` and **print the honest cost**: "Local embeddings selected — installing sentence-transformers (~250MB incl. torch); first index build downloads a ~90MB model and runs on CPU (slower than OpenAI, fully offline, zero cost)."
- README + `.env.example` get a short table: openai = fast, needs key, ~free at this scale; local = offline, no key, heavier install, slower, lower-dim (384) so slightly coarser recall.

### 4.4 Files touched for embedding fallback

```
api/config.py                       (modify: embedding_mode + models + resolved/auto-degrade)
api/services/leann_indexer.py       (modify: instance fields, _make_builder, _safe_build branch)
api/pyproject.toml                  (modify: optional-dependencies local-embeddings)
api/.env.example                    (modify: document CICADA_EMBEDDING_MODE)
api/routers/health.py               (uses resolved mode)
```

---

## 5. Claude-skill distribution sketch (`SKILL.md`)

A future distribution channel: ship Cicada as a Claude **skill** so an agent auto-loads how to use the memory dir + MCP tools without the user hand-editing config. This section is a *sketch* (the full skill is a later task), delivered as a file the install can drop into `~/.claude/skills/cicada/`.

### 5.1 File

`skill/SKILL.md` (create in repo; `install.sh --skill` copies to `~/.claude/skills/cicada/SKILL.md`). Frontmatter + body shape:

```markdown
---
name: cicada
description: >-
  Personal second-brain memory. Use when the user references something they told
  you before, asks "what do I know about X", wants to save a fact/link for later,
  or when starting a session and prior context would help. Backed by the Cicada
  MCP server (cicada-bookworm) and a local markdown knowledge graph.
---

# Cicada memory skill

## When to use
- Start of a session on a recurring topic -> call `cicada_recall` first.
- User says "remember this" / shares a decision or a link -> `cicada_save_episode`.
- User asks what you know about a person/project/tool -> `cicada_recall` then
  `cicada_recall_detail` for the full page.
- Periodically -> `cicada_check_nudges` to surface decay/conflict/clarification items.

## Tools (MCP server: cicada-bookworm)
- cicada_recall(query)          : Pass 1 — summaries + relevant pending items.
- cicada_recall_detail(entity_id): Pass 2 — the full entity page.
- cicada_save_episode(content,title): stage a memory for the next Sleep cycle.
- cicada_check_nudges(topic?)   : pending items needing the user.

## Traversal protocol (small-model friendly)
1. cicada_recall(topic). Read the summaries + "Related (one hop out)".
2. Pick the most relevant entity_id; cicada_recall_detail(entity_id).
3. Follow [[wikilinks]] / Related list -> recall_detail on those for depth.
4. Surface any returned nudges/clarifications to the user in-flow; don't dump them.

## Memory directory (read-only orientation)
~/cicada/memory/
  entities/   one markdown page per entity (YAML frontmatter + body)
  episodes/   raw captured snippets (source of truth for re-consolidation)
  inbox/      pending items the user can resolve (unified nudges+clarifications)
  leann/      vector indexes (do not edit by hand)
Do NOT write entity files directly — capture via cicada_save_episode and let the
Sleep cycle consolidate. Direct edits bypass provenance + dedup.

## Setup pointer
If the tools are missing, the MCP server isn't registered. Tell the user to run
`make install` (or `claude mcp add cicada-bookworm …`) from the Cicada repo.
```

### 5.2 Why a skill (vs. just the MCP entry)

The MCP server exposes the *tools*; the skill teaches the *policy* (when to recall, the two-pass traversal, "never hand-edit entities"). Pairing them means a fresh agent both has the tools and knows the protocol. The skill carries no secrets and no personal data — purely the procedure. `install.sh --skill` is opt-in; default install only registers the MCP server.

### 5.3 Files

```
skill/SKILL.md          (create)
scripts/install.sh      (modify: --skill copies skill/SKILL.md to ~/.claude/skills/cicada/)
```

---

## 6. Backward compatibility

- **No memory mutation.** Nothing in this axis edits entity/episode/nudge/clarification files. The live 1882 entities / 39 nudges / 33 clarifications are untouched. The menu bar only *reads* counts.
- **Embedding mode switch is rebuild-only, not destructive.** Existing OpenAI-built `leann/` indexes keep working under `openai` mode. Choosing `local` requires a rebuild (documented); it never deletes the markdown graph, only the vector sidecars on the next sleep cycle.
- **`install.sh` never clobbers `.env`** (fills missing keys only) and **never deletes `memory/`** (even `--purge` leaves it).
- **MCP merge is additive** with a `.bak` backup; an existing `cicada-bookworm` entry is preserved unless `--force`.
- **`mcp/mcp_config.json`** stays as a documented manual-fallback example (its `/path/to/cicada` placeholders are now clearly labeled "auto-filled by install.sh").
- **Dev workflow unchanged.** `swift run` + manual `uvicorn` still work; `BackendProcess`'s port-in-use guard means the app coexists with a launchd backend with zero changes.

---

## 7. Implementation order (single dev, days)

1. **`GET /healthz`** (`api/routers/health.py` + register in `main.py`). Smallest unblock for installer/doctor. (~30 min)
2. **Embedding config + indexer threading** (`config.py`, `leann_indexer.py`, `pyproject.toml`, `.env.example`). Verify `python -c "from api.services.leann_indexer import LeannIndexer; LeannIndexer(Path('memory'))"` resolves under both modes. (~half day)
3. **`StatusService` + `StatusSnapshot`** with the `/status`-or-compose fallback (`Services/StatusService.swift`). (~half day)
4. **Bookworm sprite system** (`BookwormState.swift`, `BookwormSprites.swift` transcribed from `book_worm.png`, `BookwormRenderer.swift`). Render a static frame to a template `NSImage` and eyeball it in the menu bar before animating. (~1 day, mostly pixel authoring)
5. **Rewrite `MenuBarManager`** (controller + frame timer + dropdown). (~half day)
6. **Wiring** (`CicadaApp.swift` poll task + action closures; `SleepViewModel.onStatusChanged`; `UploadOverlay` refresh). Confirm the icon actually changes when a sleep cycle runs. (~half day)
7. **`install.sh`** end-to-end on a clean `~/cicada` (steps 1–10), then `doctor.sh`, `uninstall.sh`, launchd templates, `run-sleep.sh`. Test idempotency by running install twice. (~1 day)
8. **`Makefile` targets** + README install section rewrite (replace the two-terminal dev-only flow with `make install`; keep dev flow as an appendix). (~half day)
9. **`SKILL.md`** sketch + `--skill` copy step. (~1 hour)
10. **Verify:** `swift build` green; `make doctor` all-green on a fresh install; menu bar cycles awake→sleeping(stage dots)→digesting→happy/curious/hungry against a real sleep run. (~half day)

---

## 8. Decision log (why these, briefly)

| Decision | Why |
|----------|-----|
| Code-defined `#`-grid sprites + template `NSImage` | Mascot is already 1-bit; template tinting handles dark+light bars free; no `Package.swift`/Resources change; diffable in review. |
| Pure `deriveBookwormState` function | Priority logic is testable without the menu bar; one place to reason about state precedence. |
| 30 s poll + 1 s sleep-hook hybrid | Idle is cheap (30 s); running cycles animate stage dots live via the existing 1 s `SleepViewModel` loop. |
| launchd for install, `BackendProcess` for dev | KeepAlive backend survives app quit; port-in-use guard lets both coexist with no code change. |
| `install.sh` copies repo into `~/cicada` | Self-contained install survives deleting the source checkout; `--dev` symlink keeps the fast inner loop. |
| Auto-degrade openai→local when no key | Key-less install *works* instead of silently going dark with `index_warning`. |
| Local embeddings as opt-in extra, cost stated | Honest about torch's ~250MB; doesn't force the weight on OpenAI users. |
| Skill carries policy, MCP carries tools | A fresh agent gets both the tools and the "when/how to recall, never hand-edit" protocol. |
