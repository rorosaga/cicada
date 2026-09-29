# The study desk, app zoom, Settings and Sources — design (2026-09-05)

**Owner's brief (2026-09-05, verbatim where it matters):** take the current Sleep page as
inspiration and "work on the bookworm with cute word bubble comments based on status, a pile
of books that increases based on the amount of text in episodes, see the numbers go down as
they get consolidated based on category, use proper icons and logos of the different sources
of information. The how cicada sleeps can just be something in the '?' button. I like the
history of recent consolidations, and clicking them shows what stuff got consolidated, how
much time it took, etc. Dont put graphs for the sources like in the picture. Get creative
with it… Also work on the zoom of the view… tackle any other tickets that are pending.
Re-design of sources and settings page included."

This spec turns that into five tracks, in build order. Each track is one Workflow track
(worktree, plan, critic, per-task implement + review, two-lens final review, PR to `dev`)
per `docs/goals/working-method.md`. **Workflow agents run on sonnet/haiku only** (owner,
2026-09-05); the orchestrator plans, verifies and merges.

| Track | Rows | What ships | Order / why |
|---|---|---|---|
| **A · The study desk** | G125, the brief | Sleep page rebuilt around the worm: speech bubble, book pile, per-source study list that counts down live, consolidation history with drill-down, `?` = "How Cicada sleeps", schedule modes in Settings, `reading` mascot state | First — the owner's main ask; everything else is independent of it |
| **B · App zoom** | G130 slice 1 | One `uiScale` the theme derives from, View menu ⌘+/⌘−/⌘0, Settings slider | Second — touches every view's font call, so it lands after A's new views exist |
| **C · Settings** | G122, G126 (page only), G130 slider slot | Sidebar-style Settings: General · Sleep (engine picker + schedule) · Integrations · Agents · Plans & keys | Third — Sleep settings from A and the slider from B move in |
| **D · Sources** | G124 follow-ups, brief | Logo-first grouped grid, status lights + quick actions, per-source page with "what Cicada reads" and its queue strip | Can run beside C (separate files; `Copy.swift` merges by union) |
| **E · Pending queue** | G129 slice 2, G117, G113 3–7, G118 slice 2 | Each its own track, in the order `working-method.md` §3 already gives | After A–D |

Rulings that bind every track: provenance is the vision (G118); no prices or tokens in the
app (G124); capture is deterministic (G105); the inbox asks like Claude Code asks (G115);
decay charges once; scheduled cycles never spend plan quota (TODO.md ruling 4); markdown+git
is the only source of truth; ETag ship-together; portability (no owner name, no author path);
privacy in docs.

---

## Track A — the study desk

### The idea

The Sleep page is where the owner watches the bank fill and empty. Today it is a dashboard:
a mascot card, a queue card, a schedule card, a "catching up on" list, a progress card with
four counters, and a raw episode list. The redesign makes it a **desk**: the worm sits at it
with a pile of books beside it; the pile is the queue, physically; the worm says what it is
doing; the list under the desk is what is on the pile by source; and the shelf behind it is
what has already been read (the consolidation history). Nothing on the page is a chart.

### Layout (top to bottom, max width 760 pt as today)

1. **Header** — "Sleep" + subtitle. Top-right holds **only the `?` button**; its popover is
   *How Cicada sleeps* (the five stages in one line each, what "consolidate" means, that the
   nightly schedule never spends plan quota, where the schedule lives). The global Sleep /
   Upload pair leaves this page (G125 (5)); the other pages' toolbar is untouched by this
   track — their audit is a one-line follow-up on the G125 row.
2. **The desk card** — one card, two columns.
   - Left: the bookworm at 120 pt (`BookwormView`, unchanged renderer) in the mood
     `deriveSleepPageMood` derives, with a **speech bubble** above-right of it, and the
     bracket caption under it as today.
   - Right: the **book pile** — a stack of spines, bottom-up, one spine per source category,
     each spine's height a function of the *text volume* queued from that source, coloured
     by the source's brand colour with its mark on the spine and the count at its end. While
     a cycle runs, each spine shrinks toward zero as that source's episodes are read.
   - Under both: a one-line detail (Rested % as today when idle; "Stage 2 of 5 — sorting who
     is who" plus a thin progress bar while running), then the existing error / warning /
     cancelled / cap banners, compacted.
3. **The study list card** ("On the desk") — one row per source category, largest first:
   the source's mark (real logo where one exists, `OriginMark`), its label, "oldest 3d",
   the count. While a cycle runs the row reads `12 / 188` with a thin progress bar. A chevron
   expands the row inline into that source's queued episodes (the current `EpisodeRow`, so
   the raw list survives as a per-source disclosure rather than a page-long list). The card's
   footer carries the one **Consolidate now** button (Cancel while running) and the **next-run
   line** ("Next run: tonight 03:00 · daily" / "Runs 10 min after the next import" / "Manual
   only") with a `SettingsLink` labelled *Change in Settings → Schedule*.
   No age tiles, no per-source bars — the owner asked for no source graphs.
4. **Recent consolidations card** — the last 15 Sleep cycles from git, newest first: date,
   engine mark, "+12 new · 8 updated", duration ("4 m 12 s" — from the `sleep_run` telemetry
   row when one exists, "—" otherwise), episode count. Decay-only commits (`Sleep cycle …
   (decay)`) show as their own quieter row ("decay pass"). **Clicking a row expands it**
   (fetched on demand, cached per commit): episodes by source (marks + counts), duration,
   the model(s) that authored it, sessions consolidated, and the first 30 entity chips —
   clicking a chip lands on the node in the graph (`revealEntity`, the G123 seam).

### The mascot

- New `BookwormState.reading` (G125 (1)). Title "Reading", detail "reading what's waiting".
  Sprite: an open book held low in front of the belly; frames alternate the eyes tracking
  left → right and a page-turn (the book's right half flicks). ≥ 2 differing frames, in
  palette, interval 0.5 s, glasses rim identical to the other states — the existing sprite
  tests enforce all four.
- **Sleep-page precedence** (`deriveSleepPageMood`): sleeping > error > digesting > *intake
  in flight → reading* > queue empty → happy > overdue → hungry > **reading**. `reading`
  replaces `curious(count:)` on this page only; the menu bar's `deriveBookwormState` is
  unchanged (curious there means inbox items). `store.intakeInFlight` is set by the upload
  overlay for the duration of an upload/import.
- Bracket caption for reading: `[ 188 to read ]`; colour `textSecondary`.

### The speech bubble

`sleepBubbleText(state:debt:top:stage:variant:) -> String` is pure and tested. Two or three
lines per state; the variant index is derived from stable inputs (queue count + stage), never
the clock, so the bubble changes when the state changes and never flickers. Voice: short,
warm, first person, no exclamation marks in the sad states. Examples (final copy lives in the
function):

| State | Lines |
|---|---|
| reading | "188 to read. The Safari tabs are piling up." · "Give me a night and I'll have these." |
| sleeping(1) | "Reading… 12 of 188." (with progress) |
| sleeping(2) | "Sorting out who's who." |
| sleeping(3) | "Two of these disagree. Noting it." |
| sleeping(4) | "I think I see a habit here." |
| sleeping(5) | "Filing everything away." |
| digesting | "That was a good one." |
| happy | "All read. Nothing waiting." |
| hungry | "It's been 3 days. I'm behind." · "Overdue. Wake me when you can." |
| error | "Last night didn't go well — see below." |
| awake | "Listening." |

The bubble is a rounded rectangle with a small tail toward the worm, theme surface colours,
max width 260 pt, `fixedSize(horizontal: false, vertical: true)`.

### The book pile

`bookPileLayout(_ buckets: [OriginVolume], maxBooks: Int = 8) -> [BookSpec]` is pure and
tested. `OriginVolume{origin, count, chars, remaining}`; `BookSpec{origin, height, widthFraction,
isRemainder}`. Height = `8 + 6 · log2(1 + chars / 2000)`, clamped to 8…40 pt, so a source with
one short note is one thin book and a source with 200 tabs is a fat one. Books sort largest
first; beyond `maxBooks` they fold into one grey "+N more" spine. `widthFraction = remaining /
count` while running (spines shrink from the right as episodes are read), `1` otherwise.
Reduce Motion disables the shrink animation. The pile is a `VStack` of `RoundedRectangle`s,
each with an `OriginMark` (12 pt) at the left and the count at the right; a zero-height
remainder renders nothing.

### Backend (engine-free throughout; nothing reads the bank at capture time)

1. `EpisodeQueueItem.chars: int` — `len(body)` for the pile. Older apps ignore it.
2. **Per-source countdown.** `SleepState.queue_by_origin: dict[str,int]` (this cycle's
   selected episodes grouped by `origin`) and `read_by_origin: dict[str,int]` (Stage-1 done
   per origin). `entity_extractor.extract` gains `on_episode_done: Callable[[dict], None] |
   None` fired with the episode right after the existing zero-arg `progress_callback`
   (which stays, unchanged, for its current callers/tests). Both dicts ride
   `SleepStatusResponse` (`queueByOrigin`, `readByOrigin`) and the SSE `sleep` event; the SSE
   change key gains `state.stage1_progress` so every episode read fires one event. The app's
   `SleepEventPayload` decodes both as optionals.
3. **History.** `GET /sleep/history?limit=15` (default 15, max 100): `SleepHistoryEntry` gains
   `kind` (`sleep` | `decay` | `inbox`), `entities_created`, `entities_updated`, `episodes`
   (distinct `source: ep_…` refs), `sessions`, `authors`, `duration_ms`. Counts come from one
   `git log --format=%H%x1f%aI%x1f%s%x1f%b%x1e -n <limit> --grep …` parsed **server-side**
   (the body never crosses the wire — the M1 lesson stays honoured), cached per
   `(git_head, limit)`. `duration_ms` joins the `sleep_run` ledger rows by `refs.commit`
   (a prefix match in either direction; `None` when telemetry is off or the row is missing).
   `files_changed` stays for existing callers but is no longer computed per commit with a
   `diff-tree` (it comes from the manifest lines) — the old shape is preserved, the cost
   drops.
4. `GET /sleep/history/{commit}` → `SleepCycleDetail`: the entry's fields plus `entities:
   [{id, action, trigger, source_episode}]` (first 200, `truncated`), `episodes_by_origin:
   {origin: count}` (each `ep_…` ref resolved to its `origin` from the episode's frontmatter
   through `bank_index`, `unknown` when the page is gone), `inbox_changes`. 404 for a hash
   that is not a Sleep/inbox commit; never `git show` of a diff.
5. **Schedule modes.** `ScheduleConfig` gains `mode: "manual"|"daily"|"interval"|"after_import"`
   (default derived from `enabled` when absent so an older client's PUT and an older YAML
   still load) and `interval_hours: int` (1…168, default 6). `enabled` stays as the derived
   boolean (`mode != "manual"`) so `/status.nextSleepAt` readers keep working.
   `register_job`: daily → `CronTrigger`; interval → `IntervalTrigger(hours=)`; after_import →
   an `IntervalTrigger(minutes=5)` probe that triggers a cycle when the queue is non-empty,
   idle, and the newest unprocessed episode is ≥ 10 min old ("after the import has settled")
   — no writer has to call a hook, so Telegram, uploads, hooks and connector syncs all count.
   `next_run_at` answers every mode (interval: last cycle + N h, or now + N h if never;
   after_import: newest unprocessed + 10 min, or `None` when the queue is empty). Every
   scheduled path keeps `user_triggered=False` (ruling 4).

### App wiring

- `SleepViewModel` gains `history`, `details[commit]`, `loadHistory()`, `loadDetail(_:)`;
  `load()` fetches history alongside status/episodes/schedule with the same token guard.
- `SleepQueueCard` and `SleepDebtBreakdown` are deleted; their pure functions
  (`loadState`, `groupEpisodesByOrigin`, `parseEpisodeTimestamp`) move to
  `StudyListCard.swift` / `SleepQueueModel.swift` with their tests renamed, not dropped.
- `TopBarControls` gains `showsSleep` / `showsUpload` flags (default `true`) and a `help:
  HelpContent` enum (`.actions` — today's text — or `.howSleepWorks`).
- `ContentView` threads `onSelectEntity` into `SleepView` the way it does for Sources.
- Settings → Schedule gets the mode picker (segmented: Manual · Daily · Every N hours · After
  imports) with the time picker under Daily and a stepper under Every N hours; the Sleep page
  itself carries no schedule control beyond the next-run line.

### Tests

Swift: `SleepMoodTests` (reading precedence, intake-in-flight), `SleepBubbleTests` (every
state has ≥ 2 lines, no clock dependence, count interpolation), `BookPileTests` (height curve,
remainder folding, shrink fraction, zero input), `StudyListTests` (grouping with remaining,
oldest age), `SleepHistoryDecodeTests` (older payload without the new fields still decodes;
detail decodes), `BookwormSpriteTests` states list gains `.reading`, `ScheduleModeTests`
(decode of an old `{enabled,hour,minute}` payload), `TopBarControlsTests` (flags),
`CopyConstantsTests` unchanged. Python: `test_sleep_history_detail.py` (parse a synthetic
commit body; the telemetry join; limit; 404), `test_sleep_schedule_modes.py` (load/save
round-trips, derived `enabled`, `next_run_at` per mode, the settle probe's three conditions,
`user_triggered=False` on every scheduled path), `test_sleep_progress.py` (per-origin
countdown end-to-end through `extract`), `test_sync.py` (the SSE key moves per episode).

### Not in scope (Track A)

The engine picker (Track C), the toolbar audit on Graph/Clusters (follow-up line on G125),
per-cycle *estimates* (G107 keeps them deferred on G74's trigger), sound/drag/feeding.

---

## Track B — app zoom (G130 slice 1)

- `ThemeStore.uiScale: Double` (persisted `cicada.uiScale`, clamped 0.8…1.4 in 0.1 steps;
  1.0 = today). `CicadaTheme.scale` reads it; the five font tokens and the six spacing tokens
  become computed from it (`static var`), so a change repaints every reader (the PR #49
  mechanism). Setter idempotent. **No `.id()` on the root** (the PR #49 lesson).
- `CicadaTheme.font(size:weight:design:)` + `CicadaTheme.scaled(_:)`; a mechanical migration
  of every `.font(.system(size: N …))` literal in `Sources/` to `CicadaTheme.font(size: N …)`
  (a haiku job with a grep-count before/after and a source lint that no literal remains).
  Fixed frames stay fixed in slice 1; the 1.4 cap keeps text inside them.
- `BookwormView.pointSize` snaps to the nearest multiple of 24 after scaling.
- `CommandGroup(after: .sidebar)`: *Zoom In* (⌘= and ⌘+), *Zoom Out* (⌘−), *Actual Size*
  (⌘0). A Settings slider lands in Track C's General section; until C merges it sits beside
  the theme toggle in the existing Settings tabs.
- The graph web view is untouched (slice 2 only on a measured need).
- Tests: `ThemeScaleTests` (clamp, idempotent setter, observation fires, tokens scale
  linearly, persisted value read at launch), the literal-font source lint.

## Track C — Settings

`SettingsScene` becomes a `NavigationSplitView` (sidebar of sections, selection persisted
under `cicada.settingsSection`, window 900 × 640):

1. **General** — appearance (Dark / Light), UI zoom slider (B), the demo-bank and onboarding
   re-open buttons land here when G117 ships (slots only).
2. **Sleep** — the **engine & model card** (G122): segmented Auto · Claude plan · Codex ·
   Ollama · API key with live state per option, a model field with aliases for the plan and
   `ollama list` output for Ollama, and two preview lines — "Next manual cycle: Claude plan ·
   sonnet" and "Nightly schedule: API key" — computed by the same resolver with
   `user_triggered` true/false, so ruling 4 is visible rather than a surprise. Ollama shows
   *install → start → pull a model* as three states with the exact command each (Cicada
   detects and guides; never bundles the binary). Backend: `GET/PUT /sleep/engine`
   (`{mode, model, candidates:[{id,label,available,connected,models,detail}], preview:{manual,
   scheduled}}`), prefs in `~/.cicada/connections.json` (never `api/.env`), and
   `engine_select` reads prefs before env — an explicit `CICADA_LLM_MODE` still wins so a
   fresh install's `.env` and the UI never disagree. Then the schedule editor from Track A.
3. **Integrations** (G126, the page only) — categories over the one channel registry:
   *Chat & agents* · *Browsers* · *Social & saved* · *Feeds & calendars* · *Messaging* ·
   *Files & imports*. One logo-first row per channel with live state (connected · last sync ·
   count · error), and the action the channel supports: Connect / Disconnect for OAuth
   connectors (reusing `ConnectorSetupPanel` in a popover), Sync now / Poll now where
   `actions` says so (the `ChannelSourceView` code paths), and *Import in Feed →* for one-shot
   exports (the Feed's `+` sheet stays the place for a one-shot act — the G126 ruling). No new
   adapters in this track; each is its own row when it starts.
4. **Agents** — `ConnectView` as is.
5. **Plans & keys** — `ConnectionsView` as is.

`Copy.schedule` becomes `Copy.sleepSettings` ("Sleep"), and `settingsSchedule` →
`settingsSleep` ("Settings → Sleep"); `CopyConstantsTests` and every pointer update together.

## Track D — Sources

- Cards use `OriginMark` (real logo / drawn glyph / symbol) instead of a bare SF symbol; the
  grid is grouped under section headers by kind (the backend's `KIND_ORDER`); the connected
  dot becomes the G129 status light where a watch exists and a plain light elsewhere; a hover
  reveals *Sync now* / *Poll now* for channels whose `actions` include them.
- The per-source page opens with the logo, one honest sentence of *what Cicada reads from
  this* (a Swift table keyed by source id — no network), a **queue strip** ("12 waiting for
  Sleep" from `sleepVM.queuedEpisodes` filtered to the source's origins, with *Consolidate
  now*) and a *consolidated so far* line (episodes → entities from the overview row), then the
  existing channel state / conversations / items.
- Contributors and Advanced are unchanged (the feedback tile slot stays for G113).

## Track E — the pending queue

In `working-method.md` §3 order: **G129 slice 2** (bookmark deletions; both rails on the
row), **G117** first-run onboarding (reuses C's engine card as step 1 and C's Integrations
page filtered to "connect one thing" as step 2), **G113 slices 3–7** (resume from the paused
worktree per its entry), **G118 slice 2** (the provenance viewer). Docs: the "graph re-lays
out on every return" entry in TODO.md's known-broken list is stale — `ContentView` keeps the
graph mounted since 2026-09-03 — and is removed in Track A's docs task.

## Decisions taken without the owner (autonomous session — review at PR time)

1. `after_import` is implemented as "when the queue has settled for 10 minutes", probed every
   5 minutes, rather than a hook every writer must call.
2. The Sleep page loses its pause/resume toggle and its four stage counters; both live in
   Settings → Schedule and in the consolidation history respectively.
3. The book pile encodes *characters queued* (log scale), not episode count — the count is on
   the study list; two encodings of the same number would be a chart.
4. On the Sleep page `reading` replaces `curious`; the menu bar keeps `curious` for inbox
   items.
5. Track B caps zoom at 1.4 (not 1.6) because fixed-width frames are left alone in slice 1.
6. Prefs-chosen engines obey ruling 4 exactly: a scheduled cycle never runs on a plan unless
   `CICADA_LLM_MODE` says so in `api/.env`; the Settings card shows both previews.
