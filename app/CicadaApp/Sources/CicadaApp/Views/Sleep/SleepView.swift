import SwiftUI

// MARK: - The page's arrangement (Track Z Z3)

/// The Sleep page's text column (Track Z R-Z6 / §4.1; DR-36): 760 pt holds the room's sentence, its control and its
/// whisper, and Past reads' rows. The room's art is no longer bound by it — out of its card since the Sleep redesign
/// (2026-10-16), it takes up to `artMaxWidth` at a whole point per cell (`artScale`, `SleepLayoutTests`).
enum SleepLayout {
    static let contentWidth: CGFloat = 760
}

// MARK: - Liveness (G125 v3 Task 8 — spec R-A12)

/// Whether what the page is showing is a live reading or a last-known-good
/// one, and — when it is the latter — the moment it was good at.
///
/// The Store's whole design is last-known-good projections that **never
/// blank** (CLAUDE.md, the sync engine). The cost of that promise is that a
/// dead backend looks exactly like a healthy one. This is the honest tax:
/// one desaturation step and a chip that dates the page, so a reader can tell
/// "nothing has changed" from "nothing is arriving" without the page ever
/// throwing away the numbers it already has.
enum SleepLiveness: Equatable {
    case live
    case stale(asOf: Date)

    /// ONE step (R-A12). Named rather than written into a `.saturation(0.85)`
    /// at each call site so "one step" stays one number.
    static let staleSaturation: Double = 0.85

    /// How old the last backend confirmation has to be before the page will
    /// call itself stale (final review, finding 1).
    ///
    /// **`store.isConnected` is not "the backend is down" — it is "the SSE
    /// stream is not currently open."** `SyncEngine.start` sets it false for
    /// the *whole* backoff window (1 s doubling to 30 s) while the loop inside
    /// that window keeps polling `GET /sync/version` every 3 s and keeps
    /// refreshing whatever changed. So every backend restart and every dropped
    /// stream flipped the flag and this page printed "Not connected — showing
    /// the last reading · as of 16:12" with 16:12 seconds old: a warning
    /// contradicted by its own timestamp, on the one feature here built to be
    /// honest about freshness.
    ///
    /// 60 s is chosen to clear the transport's own worst case with room —
    /// `SyncEngine.pollInterval` is 3 s and `maxBackoff` 30 s — so a reconnect
    /// never trips the chip, while a backend that has genuinely stopped
    /// answering trips it within a minute of its last confirmation (and
    /// immediately, if contact was already older than that).
    ///
    /// No timer is needed to make the chip appear: the reconnect loop re-assigns
    /// `store.isConnected` on every backoff iteration, and an `@Observable`
    /// write re-evaluates the body whether or not the value changed. The motion
    /// budget's "idle is still" (rule 1) survives — a settled, connected page
    /// still costs zero redraws.
    static let staleAfter: TimeInterval = 60

    var saturation: Double {
        switch self {
        case .live: 1.0
        case .stale: Self.staleSaturation
        }
    }

    var asOf: Date? {
        if case .stale(let date) = self { return date }
        return nil
    }

    /// The page draws several domains, each with its own
    /// `Snapshot.refreshedAt`. The chip is ONE number, so it takes the OLDEST
    /// of them: naming the newest would date the page by its freshest card and
    /// quietly overstate how current the stalest one is. A domain the backend
    /// has never confirmed contributes nothing — it has no reading to be
    /// stale, and `sleepLiveness` refuses to print a chip when they all say
    /// nothing.
    ///
    /// **`refreshedAt`, never `loadedAt`** (review round 2). `loadedAt` moves
    /// on a disk-cache hydrate too, so a cold launch against a stopped backend
    /// stamped both domains with the launch time and this chip printed the
    /// minute the app opened over data that could be days old — the fabricated
    /// timestamp the docstring below refuses, in the state the feature exists
    /// for.
    static func stalestRefreshedAt(_ dates: Date?...) -> Date? {
        dates.compactMap { $0 }.min()
    }
}

/// R-A12. Three refusals, in order:
///
/// - Connected → `.live`. Nothing to disclose.
/// - **A failed CYCLE is on screen → `.live`, even disconnected.** The page is
///   reporting news the reader can act on, and news at 85% saturation is a
///   warning whispered. `isError` means `sleepVM.lastError` — `status.error`,
///   the last cycle's own failure — and **never** the transport failure in
///   `sleepVM.errorMessage`. Review round 1 caught the confusion: a stopped
///   backend sets `errorMessage` on every `load()`, so feeding that in made
///   liveness inert in exactly the case it exists for, and *intermittently* —
///   the chip appeared until the next fetch failed, then vanished. The error
///   banner's own contrast is not this function's job: `SleepDetails` keeps
///   Last cycle outside every `.saturation` group, so both errors render at
///   full contrast whatever this returns.
/// - **The backend has never confirmed anything → `.live`.** There is no hour
///   to print, and a chip reading "as of 00:00" would be a fabricated
///   timestamp — the same refusal `—` carries everywhere else on this page
///   (P18). `refreshedAt` is what makes this refusal real: review round 2
///   caught the caller feeding `Snapshot.loadedAt`, which a disk hydrate
///   stamps, so a cold launch against a stopped backend printed the launch
///   minute over data of any age. A never-refreshed page now falls through
///   here and shows no chip at all.
///
/// - **The last confirmation is recent → `.live`.** Final review, finding 1:
///   `isConnected` goes false for the whole reconnect backoff while the poll
///   loop inside it is still talking to a healthy backend, so keying the chip
///   off the flag alone made it fire on every backend restart and every
///   dropped stream — dating the page by a timestamp seconds old. The claim
///   this page makes is about *freshness*, so it is freshness that decides:
///   nothing is called stale until the backend has been silent for
///   `SleepLiveness.staleAfter`.
///
/// `now` is injected rather than read from the clock so the function stays
/// pure and testable (the R8 rule the speech bubble already follows). It is
/// the fourth refusal that uses it; the call site passes the default, which is
/// re-read on every body evaluation.
func sleepLiveness(isConnected: Bool,
                   refreshedAt: Date?,
                   isError: Bool,
                   now: Date = Date()) -> SleepLiveness {
    guard !isConnected, !isError, let refreshedAt,
          now.timeIntervalSince(refreshedAt) > SleepLiveness.staleAfter else { return .live }
    return .stale(asOf: refreshedAt)
}

// MARK: - Sleep — the room, and everything it reads (G125; the Sleep redesign, 2026-10-16)

/// **The page (owner approval 2026-10-16, DESIGN_RULES §9 — room-over-list).** One scroll: the eyebrow ("Sleep · 42
/// waiting · last read 2 h ago" — the page title retired), the study room out of its card and drawn at a
/// whole 5/4/3 pt per cell by the column's width, the room's three lines (the sentence, the one control, the whisper),
/// then the tab row — sticky once the room scrolls away — and the selected list: Waiting, Saved (the Feed's list),
/// Videos (the Feed's Videos and its watch run) or Past reads (Details' Last cycle, Readout and Past nights). Opening
/// a saved item (or the watch run) collapses the list to the triage column beside its detail, the tab row riding the
/// eyebrow; the Reader is the third column (`hostsOwnReader`). Esc closes the rightmost (DR-28).
///
/// **The motion budget (G125, TODO ruling 18).** State art may loop; chrome
/// settles within 400 ms and the active stage pulse stays capped at 1.2 s.
/// Sprite frames stay inside `CicadaMotion`'s caps: beats within 800 ms, the
/// perk within 400 ms, and yawn/stretch within 1.6 s. Sheet tests check every
/// frame and tag; each layer redraws only at its frame boundaries. A tab switch and
/// every keyboard path never animate (DR-60).
///
/// Reduce Motion holds sprites at their key frame, suppresses beats and
/// transitions, and jumps the weather and value-driven settles. Low Power
/// plays every frame at half speed; unseen or host-paused sprites do not tick.
/// `SleepNumbersLintTests` retains the no-transform and literal-duration rails.
///
/// **No spinner where a real count exists.** A `ProgressView` on this page
///    appears only where there is genuinely nothing to count yet: the queue
///    before its first fetch, a history row's detail mid-load, and the
///    Consolidate/Cancel buttons' own in-flight state.
struct SleepView: View {
    @AppStorage(SceneryMode.defaultsKey) private var scenerySourceRaw = SceneryMode.localWeather.rawValue
    @AppStorage(ManualScenery.timeKey) private var sceneryTimeRaw = "day"
    @AppStorage(ManualScenery.baseKey) private var sceneryWeatherRaw = "sunny"
    @AppStorage(ShellMetrics.labelledKey) private var labelledSidebar = false

    @Binding var selectedTab: AppTab
    /// Entity chips inside the consolidation history's expanded detail land
    /// here (mirrors `SourcesPageView`'s own closure at `ContentView.swift`)
    /// — jump to Graph and open the card, exactly like an Ask citation.
    var onSelectEntity: ((String) -> Void)?

    @Environment(SleepViewModel.self) private var sleepVM
    /// R-HS7 / R-HS12 — the engine menu's model, the one `EngineChooser` reads; its response is the
    /// page's first source for every engine line.
    @Environment(SleepEngineViewModel.self) private var engineVM
    @Environment(AppRouter.self) private var appRouter
    // H1: the lists and the room must agree on one live reading of the queue. `Store.status`/`Store.sleepEvent` are
    // the SSE-live sources; reading them here (instead of only `sleepVM.queuedEpisodes.count`, fetched once per
    // visit) keeps every readout on the page from disagreeing when a capture lands while it's open.
    @Environment(Store.self) private var store
    /// The Feed's model since it folded into Sleep's Saved and Videos tabs (2026-10-16): the rows, the sort, the kind,
    /// find's text and the open item.
    @Environment(FeedViewModel.self) private var feedVM
    /// G162 — the video states the rows, the strip and the watch run read.
    @Environment(VideoStateCache.self) private var videoCache
    /// R-IB22 — an export the person is waiting on keeps Saved up while nothing is saved: its strip heads that tab.
    @Environment(ExportWaitStore.self) private var exportWaits
    @Environment(ProvenanceRouter.self) private var provenance
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    /// Track Z Z10 — Increase Contrast hides the optional sky band (§11).
    @Environment(\.colorSchemeContrast) private var contrast
    @State private var loadedOnce: Bool = false
    /// When the page last refetched for a moved Sleep time (`SleepPageRefresh`).
    @State private var lastRefetch: Date?
    // PR #19 review: rapid live-count changes (a capture landing, then
    // another one right behind it) fired an untracked `sleepVM.load()` Task
    // per change with no cancellation. Mirrors `UsageViewModel.rangeTask`:
    // cancelling the previous reconcile the moment a newer one supersedes it
    // frees the abandoned in-flight work instead of leaving it to run to
    // completion for nothing — `SleepViewModel.load()`'s own `loadToken`
    // guard is the real backstop that makes a stale response harmless either
    // way (cancellation isn't guaranteed to unwind a parked continuation, in
    // tests or otherwise).
    @State private var reconcileTask: Task<Void, Never>?
    // G106 amendment: set the moment this view's own observation of
    // `sleepVM.status?.status` sees a running -> idle transition. Purely
    // local — `SleepViewModel.onCycleCompleted`/`Store.onStatus` are both
    // single-slot closures already claimed elsewhere (graph refresh, the
    // menu-bar bookworm respectively), so this view tracks its own edge via
    // `.onChange` instead of contending for either slot.
    @State private var justFinishedAt: Date?
    /// The tab the person chose this visit; `nil` follows the page's state (Waiting while anything waits, else Past
    /// reads — `SleepTab.resolve`). Page-local: a fresh visit opens on what the room is about.
    @State private var chosenTab: SleepTab?
    /// A tail link, a spine or a hand-off asked for the lists: scroll the tab row to the top once it is drawn.
    @State private var scrollToTabs = false
    /// DR-46 — find over the selected list of saved items.
    @State private var findOpen = false
    /// R-DL16 — bumps when a hand-off lands on a saved item, so the list scrolls it into view.
    @State private var landingToken = 0
    @FocusState private var focus: ListFocus?
    /// G162 — the watch run: the picker and its card take the list and the detail while it is on.
    @State private var run = VideoRunModel()
    /// R-DL14 — the one-shot import's sheet (⌘N, the `+`, an Integrations hand-off).
    @State private var showAddSheet = false
    @State private var sheetTile: AddSourceTile?
    /// Track Z Z5 — the room's interaction state (gaze, perk, the answer
    /// ladder). Page-local `@State`: a tab switch tears it down, so an answer
    /// never outlives the visit it was asked in.
    @State private var room = RoomModel()
    /// G212 — the machine whose queue Waiting shows (nil: every machine's); the machines themselves are
    /// `sleepVM.machines`, polled while the page shows.
    @State private var openMachine: String?

    private static let tabsAnchor = "sleep.tabs"
    private static let topAnchor = "sleep.top"
    /// Say it once — bumps when Sleep is clicked again in the rail, so the page scrolls back to the room.
    @State private var toTop = 0

    /// Three stages, so the type checker never faces one chain of every modifier (ContentView's `lifecycleStage`
    /// reason): the page and its sheet, then the hand-offs, then the load and the cycle's edges.
    var body: some View {
        let page = resolvePage()
        return lifecycle(handoffs(pageStack(page)), page: page)
    }

    private func pageStack(_ page: SleepPageModel) -> some View {
        let tab = currentTab(page)
        return ZStack {
            // No .ignoresSafeArea(): the title bar is darkened at the window level
            // (CicadaApp). Ignoring the safe area here pushed content under the menu
            // bar and stretched the window to full screen height.
            CicadaTheme.background

            // Track Z Z10 (spec decision 16) — the optional sky band: behind
            // everything, fixed across the top, following the window's weather.
            // `SkyBand.ships` is the one switch (Z-B16).
            if SkyBand.isDrawn(contrast: contrast) {
                VStack(spacing: 0) {
                    SleepSkyBand(scenery: Scenery.resolve(mode: SceneryMode.stored(scenerySourceRaw),
                        clock: SceneStore.shared.phase,
                        forecast: LocalWeatherReader.shared.base(for: SceneStore.shared.timeZoneIdentifier),
                        mood: page.mood, manual: ManualScenery(timeRaw: sceneryTimeRaw, baseRaw: sceneryWeatherRaw)))
                    Spacer(minLength: 0)
                }
            }

            columns(page, tab: tab)
        }
        // From a leaf, not the page (DS-3c final review): a publisher on the page's if/else rebuilt every column on each
        // flip of `findOpen`. Only a list of saved items has a find.
        .background { Color.clear.publishesPageFind(enabled: !findOpen && tab.hasFind) { findOpen = true } }
        .onChange(of: findOpen) { _, isOpen in if !isOpen { feedVM.searchText = "" } }
        // I4 — a mood change resets the ladder: an answer about the state that just ended is no longer true, and any
        // feed line about a moment that has passed (Z-B11). On the page, not the room: the room may have scrolled away.
        .onChange(of: page.mood.caseName) { _, _ in room.dismissSlot() }
        .sheet(isPresented: $showAddSheet) {
            AddSourceSheet(initialTile: sheetTile, onClose: { showAddSheet = false }, flowOnly: sheetTile != nil)
        }
    }

    private func handoffs(_ content: some View) -> some View {
        content
        .onAppear {
            // A search left from the last visit would keep filtering with no field on screen (§5.5).
            feedVM.searchText = ""
            consumeDetailsRoute(); consumePendingAddSource(); consumeLanding(); consumeVideoChooser()
            feedVM.reconcile()
        }
        .onChange(of: appRouter.pendingSleepDetails) { _, _ in consumeDetailsRoute() }
        // Say it once — Sleep clicked again in the rail: the room, the list its state chooses, nothing open.
        .onRailReselect(.sleep, router: appRouter) { popToRoot() }
        .onChange(of: appRouter.pendingAddSource) { _, _ in consumePendingAddSource() }
        .onChange(of: appRouter.pendingSavedItem) { _, _ in consumeLanding() }
        .onChange(of: appRouter.pendingVideoChooser) { _, _ in consumeVideoChooser() }
        .onChange(of: feedVM.items.map(\.id)) { _, _ in feedVM.reconcile() }
        .onChange(of: videoRows.map(\.id)) { _, ids in run.reconcile(present: Set(ids)) }
        // G162 — the video states the rows, the strip and the run read (a 304 costs nothing).
        .task { await videoCache.refresh() }
        // G212 — the machines strip, asked while the page shows; a failed poll keeps the last answer.
        .task {
            while !Task.isCancelled {
                await sleepVM.loadMachines()
                try? await Task.sleep(for: .seconds(CicadaTiming.machinePoll))
            }
        }
    }

    private func lifecycle(_ content: some View, page: SleepPageModel) -> some View {
        reconciles(followsRun(loads(content)))
    }

    /// The page's loads and Sleep's running → idle edge — split from `lifecycle`, whose one modifier chain sat near
    /// what the type checker solves in reasonable time on a slower release runner.
    private func loads(_ content: some View) -> some View {
        content
        // Keyed on the Store's newest Sleep time and Sleep's state too: a cycle this page did not start (a scheduled
        // drain, the CLI) that moves or finishes while it is open reruns this, so Past reads' Last cycle rereads what it
        // describes — at most every 30 s while a run commits batch after batch, and always when it ends.
        .task(id: refreshKey) {
            if !loadedOnce {
                loadedOnce = true
                lastRefetch = Date()
                await sleepVM.load()
                await sleepVM.loadQueue()
                if let id = detailRunId { await sleepVM.loadRunDetail(id, freshness: detailRunFreshness) }
            } else if SleepPageRefresh.shouldRefetch(running: store.status.value?.sleep.status == "running",
                                                     last: lastRefetch, now: Date()) {
                lastRefetch = Date()
                await sleepVM.refreshStatus()
                await sleepVM.loadHistory()
            }
            // R-HS12 — every visit, unconditionally: the chooser's response may have been loaded
            // long before (Home's Getting started loads it at launch), and the page reads it FIRST,
            // so a stale one would hold the button, the lamp and the answers on an old engine. The
            // GET is engine-free, and `EngineChooser` re-syncs from `vm.response` (`onChange`), so
            // a reload never stomps a choice.
            await engineVM.load()
        }
        // G106 amendment + Track Z §6.5 / Z-P17. This view's own edge
        // detection — see `justFinishedAt`'s declaration for why it can't
        // reuse `SleepViewModel.onCycleCompleted` or `Store.onStatus`.
        // `justFinishedAt` is stamped on every running → idle edge as before:
        // `deriveSleepPageMood` alone decides that a cancel never chews.
        // Task 8 review r1: the baseline a completion is compared against is
        // taken at the START edge — the backend commits several seconds
        // before it reports idle (the engine-independent tail runs in
        // between), and a reconcile `load()` in that window already brings
        // the new commit, so an idle-edge baseline would be the commit
        // itself. The end edge then resolves against the history in hand,
        // and the history observer below catches a commit that lands later.
        .onChange(of: sleepVM.status?.status) { oldValue, newValue in
            if oldValue == "running" && newValue == "idle" { justFinishedAt = Date() }
            if newValue == "running" && oldValue != "running" {
                room.cycleStarted(baseline: lastCycleEntry(sleepVM.history)?.commitHash,
                                  historyLoaded: sleepVM.historyLoaded)
            }
            if oldValue == "running" && newValue != "running" {
                let real = isRealCompletion(old: oldValue, new: newValue,
                                            cancelled: sleepVM.status?.cancelled == true,
                                            error: sleepVM.status?.error,
                                            drainStop: sleepVM.status?.drain?.stop?.reason)
                if room.cycleEnded(real: real, edgeBaseline: lastCycleEntry(sleepVM.history)?.commitHash,
                                   history: sleepVM.history) != nil {
                    celebrateCompletion()
                }
            }
        }
    }

    /// The pause, Waiting's rows and an open run's detail follow the run while the page is open.
    private func followsRun(_ content: some View) -> some View {
        content
        // Sleep page v5 — a pause appears, is armed or is cleared with no status change (H3): the status refetch is
        // app-wide (`Store.onSleepPausedChanged`, wired in `CicadaApp`); the page only announces a pause (A11).
        .onChange(of: store.sleepEvent?.paused) { old, new in
            if old == nil, new != nil { AccessibilityNotification.Announcement(Copy.SleepV5.pausedAnnouncement).post() }
        }
        // Waiting's per-conversation rows follow the run's counts (M3).
        .onChange(of: queueKey) { _, _ in
            Task { @MainActor in await sleepVM.loadQueue() }
        }
        // A run's detail follows the run: a new run, more filed, a pause, a Continue or the end refetches it, so a
        // detail read while paused never outlives the pause (and the finished-only rows appear once it ends).
        .onChange(of: detailRunId.map { $0 + "#" + detailRunFreshness }) { _, _ in
            guard let id = detailRunId else { return }
            Task { @MainActor in await sleepVM.loadRunDetail(id, freshness: detailRunFreshness) }
        }
    }

    /// The history and the live unprocessed count reconcile the page (split from `followsRun` for the type checker,
    /// like `loads`).
    private func reconciles(_ content: some View) -> some View {
        content
        .onChange(of: sleepVM.history) { _, history in
            if room.resolveCompletion(history: history) != nil { celebrateCompletion() }
        }
        // PR #19 review: the room's pile reads SSE-live `store.status`
        // while Waiting's rows stay pinned to whatever `sleepVM.load()` last
        // fetched. A capture (or another Sleep cycle finishing elsewhere)
        // bumps the live count without touching the rows, so the two
        // contradict each other for as long as the page stays open. One
        // freshness model: whenever the live unprocessed count disagrees
        // with the loaded rows, refetch.
        .onChange(of: store.status.value?.episodes.unprocessed) { _, newValue in
            if Self.queueNeedsReconcile(liveUnprocessed: newValue,
                                        loadedQueuedCount: sleepVM.queuedEpisodes.count) {
                // Every new count change supersedes whichever reconcile is
                // still in flight — cancel it and start fresh so only the
                // newest count's fetch can ever publish rows, and a count
                // that changes again mid-load still gets its own attempt
                // rather than being silently dropped.
                reconcileTask?.cancel()
                reconcileTask = Task { @MainActor in await runReconcile() }
            }
        }
    }

    // MARK: The columns (§5.3)

    /// With nothing open, the list column IS the page — the room above its lists, one scroll. With a saved item (or
    /// the watch run) open, the room has scrolled away: the tab row rides the eyebrow, the list is the triage column
    /// and the item the detail. The Reader is the trailing column in both.
    private func columns(_ page: SleepPageModel, tab: SleepTab) -> some View {
        let open = hasDetail(tab)
        return ProgressiveColumns(hasDetail: open, hasTrailing: provenance.isPresented,
                                  navWidth: ShellMetrics.navWidth(labelled: labelledSidebar),
                                  wideTriage: inRun ? VideoRunLayout.pickerWidth : nil) { plan in
            if open { openEyebrow(page, tab: tab, plan: plan) }
        } list: { plan in
            if open {
                openList(tab, plan: plan)
            } else {
                browse(page, tab: tab, plan: plan)
            }
        } detail: { plan in
            if inRun {
                // Not in a ScrollView: the card scrolls its own body and keeps its footer pinned (VideoRunLarge).
                VideoRunCard(model: run, rows: videoRows, padding: plan.cardPadding, onLeave: { leaveRun() })
                    .frame(maxWidth: .infinity)
                    .padding(.horizontal, plan.gutter)
                    .padding(.bottom, CicadaTheme.scaled(72))
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
                    .focusable()
                    .focusEffectDisabled()
                    .onExitCommand { escape() }
                    .focused($focus, equals: .detail)
            } else if let item = feedVM.openItem {
                itemDetail(item, tab: tab, plan: plan)
            }
        } trailing: { _ in
            ReaderColumn().focused($focus, equals: .reader)
        }
    }

    /// The page with nothing open: the eyebrow, the room and its three lines, then the sticky tab row over the
    /// selected list (DESIGN §3.1). `LazyVStack`'s pinned header is what keeps the tab row under the titlebar once the
    /// room scrolls away.
    private func browse(_ page: SleepPageModel, tab: SleepTab, plan: ColumnPlan) -> some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 0, pinnedViews: [.sectionHeaders]) {
                    eyebrowRow(page, gutter: plan.gutter)
                        .id(Self.topAnchor)
                    roomBlock(page, columnWidth: plan.list - 2 * plan.gutter)
                        .padding(.horizontal, plan.gutter)
                        .padding(.bottom, CicadaTheme.spacingXL)
                        // R-A12: `.saturation` is UNCONDITIONAL, at the identity 1.0 while live — an `if` around it
                        // would change the room's structural identity and rebuild it every time the connection flaps.
                        .saturation(liveness.saturation)
                    Color.clear.frame(height: 0).id(Self.tabsAnchor)
                    Section {
                        listContent(page, tab: tab, plan: plan)
                    } header: {
                        stickyTabRow(page, tab: tab, gutter: plan.gutter)
                    }
                }
                .padding(.bottom, CicadaTheme.scaled(72))
            }
            // A tail link, a spine or a hand-off asked for the lists: once they are drawn, bring the tab row to the
            // top in one frame (DESIGN §3.5 — "opening a row scrolls the tab row to the top in one frame").
            .onChange(of: toTop) { _, _ in Instant.run { proxy.scrollTo(Self.topAnchor, anchor: .top) } }
            .task(id: scrollToTabs) {
                guard scrollToTabs else { return }
                DispatchQueue.main.async {
                    Instant.run { proxy.scrollTo(Self.tabsAnchor, anchor: .top) }
                    scrollToTabs = false
                }
            }
        }
        .listKeys(move: { move($0, in: tab) }, enter: { false }, escape: { escape() })
        .focused($focus, equals: .list)
    }

    /// The page's eyebrow (DR-25, DR-26 — the first item, where the title used to be), with the staleness chip at its
    /// right while the backend is not answering (R-A12). The subtitle the title carried lives on as its hint.
    private func eyebrowRow(_ page: SleepPageModel, gutter: CGFloat) -> some View {
        EyebrowRow(eyebrow: SleepEyebrow.text(waiting: waitingCount, lastSleepAt: store.status.value?.lastSleepAt,
                                              now: .now),
                   horizontalPadding: gutter) {
            // R-A12: the chip explains the dimming below it, so it stays at full contrast and sits outside every
            // desaturated group.
            if let asOf = liveness.asOf { stalenessChip(asOf) }
        }
        .accessibilityHint(Copy.sleepSubtitle)
    }

    /// The tab row as the list's pinned header: on the page ground, so rows scrolling under it never show through.
    private func stickyTabRow(_ page: SleepPageModel, tab: SleepTab, gutter: CGFloat) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            SleepTabRow(tabs: tabRowTabs(page), selected: tab, select: { selectTab($0) },
                        findOpen: $findOpen, onAdd: { openSheet(nil) })
            if findOpen && tab.hasFind {
                PageFindRow(text: Binding(get: { feedVM.searchText }, set: { feedVM.searchText = $0 }),
                            isOpen: $findOpen, prompt: Copy.Lists.findFeed)
            }
            Divider().background(CicadaTheme.border)
        }
        .padding(.top, CicadaTheme.spacingSM)
        .padding(.horizontal, gutter)
        .padding(.bottom, CicadaTheme.spacingSM)
        .background(CicadaTheme.bgBase)
    }

    /// The selected list at the page's width (STATE 0).
    @ViewBuilder
    private func listContent(_ page: SleepPageModel, tab: SleepTab, plan: ColumnPlan) -> some View {
        let rowInset = ListInsets.of(.wide).leading
        switch tab {
        case .waiting:
            let machine = sleepVM.machines.first { $0.id == openMachine }
            let machineEpisodes = MachinesStrip.episodes(sleepVM.queuedEpisodes, machine: machine)
            SleepWaitingList(page: page, liveness: liveness, episodes: machineEpisodes,
                             machineRows: machine == nil ? nil
                                 : studyRows(queued: machineEpisodes, queueByOrigin: [:], readByOrigin: [:],
                                             running: false),
                             onSelectEntity: onSelectEntity, room: room, queue: sleepVM.queue,
                             showsRun: showsRunBlock(page), runPaused: sleepVM.isPaused,
                             ownerReady: ownerReady(page), onRetryParked: retryParked,
                             onSeeOwnerPage: ownerEntityId.map { id in { onSelectEntity?(id) } })
                .padding(.horizontal, plan.gutter)
                .padding(.top, CicadaTheme.spacingSM)
        case .saved:
            if !searching {
                // R-IB22 — the exports the person is waiting on, where the Feed showed them: Home's Getting started
                // drops them once it graduates, and the menu bar's line cannot be stopped or dropped on.
                ExportWaitStrip()
                    .padding(.horizontal, rowInset + CicadaTheme.scaled(10))
                    .padding(.top, CicadaTheme.spacingSM)
            }
            FeedRowsContent(items: feedVM.visible, style: .wide, searching: searching, now: .now,
                            openId: feedVM.columns.openId, open: { open($0) })
                .padding(.horizontal, rowInset)
                .padding(.bottom, CicadaTheme.scaled(RowMetrics.twoLineGap))
        case .videos:
            if !searching && !videoCache.isGone {
                // G162 — the watch run's door (the Feed's Videos strip).
                VideosStrip(summary: videoCache.summary, choose: { beginRun() })
                    .padding(.horizontal, rowInset + CicadaTheme.scaled(10))
                    .padding(.vertical, CicadaTheme.spacingSM)
            }
            FeedRowsContent(items: visibleVideos, style: .wide, searching: searching, now: .now,
                            openId: feedVM.columns.openId, open: { open($0) })
                .padding(.horizontal, rowInset)
                .padding(.bottom, CicadaTheme.scaled(RowMetrics.twoLineGap))
        case .pastReads:
            SleepPastReads(page: page, liveness: liveness, pageError: pageError, status: sleepVM.status,
                           history: sleepVM.history, details: sleepVM.details, expanded: sleepVM.expanded,
                           onToggleHistory: toggleHistory, onSelectEntity: onSelectEntity, runRows: runRows(page),
                           runPaused: sleepVM.isPaused, onRetryParked: retryParked,
                           runDetails: sleepVM.runDetails, expandedRun: sleepVM.expandedRun,
                           onToggleRun: toggleRun,
                           items: sleepVM.consolidated, itemsFailed: sleepVM.consolidatedFailed,
                           onLoadItems: { key in Task { @MainActor in await sleepVM.loadConsolidated(key) } })
                // DR-36 — key–value rows and prose keep the 760 pt text column.
                .frame(maxWidth: SleepLayout.contentWidth, alignment: .leading)
                .padding(.horizontal, plan.gutter)
                .padding(.top, CicadaTheme.spacingSM)
        }
    }

    /// Beside an open item: the eyebrow says where the list is, the tabs and the tools ride it (DR-25).
    @ViewBuilder
    private func openEyebrow(_ page: SleepPageModel, tab: SleepTab, plan: ColumnPlan) -> some View {
        if inRun {
            // G162 — the run's eyebrow: "Sleep · Videos · Choosing · 5 selected" or "… · Watch run · 2 of 5 recorded",
            // the picker's tabs (the page's tabs give way — never two tab groups), and one ×.
            EyebrowRow(eyebrow: run.eyebrow(summary: videoCache.summary), horizontalPadding: CicadaTheme.spacingXL) {
                HStack(spacing: CicadaTheme.spacingXS) {
                    TextTabs(tabs: run.tabs(videoRows),
                             selection: Binding(get: { run.mode == .choosing ? run.tab : nil },
                                                set: { t in Instant.run { run.chooseTab(t ?? run.tab) } }))
                        .accessibilityLabel(Copy.Videos.tabsLabel)
                    IconButton(systemName: "xmark", help: Copy.Videos.leaveChoosing) { leaveRun() }
                        .padding(.leading, CicadaTheme.spacingSM)
                }
            }
        } else {
            EyebrowRow(eyebrow: openEyebrowText(tab), horizontalPadding: CicadaTheme.spacingXL) {
                SleepTabRow(tabs: tabRowTabs(page), selected: tab, select: { selectTab($0) }, findOpen: $findOpen,
                            onAdd: { openSheet(nil) })
            }
        }
    }

    private func openEyebrowText(_ tab: SleepTab) -> String {
        tab == .videos
            ? FeedEyebrow.text(total: videoItems.count, kind: nil, visible: visibleVideos, openId: feedVM.columns.openId,
                               searching: searching, tab: Copy.SleepTabs.videos)
            : feedVM.eyebrow(searching: searching)
    }

    @ViewBuilder
    private func openList(_ tab: SleepTab, plan: ColumnPlan) -> some View {
        if inRun {
            VideoRunList(model: run, rows: videoRows, style: plan.listStyle, escape: { escape() })
                .focused($focus, equals: .list)
        } else {
            FeedListColumn(style: plan.listStyle, findOpen: $findOpen, searching: searching, landingToken: landingToken,
                           items: listItems(tab), open: { open($0) }, move: { move($0, in: tab) },
                           focusDetail: { focus = .detail }, escape: { escape() })
                .focused($focus, equals: .list)
        }
    }

    private func itemDetail(_ item: MediaFeedItem, tab: SleepTab, plan: ColumnPlan) -> some View {
        ScrollView {
            FeedItemDetail(item: item, padding: plan.cardPadding,
                           hiddenListCount: plan.listHidden ? listItems(tab).count : nil,
                           onShowList: { showList() }, onClose: { closeItem() })
                .frame(maxWidth: .infinity)
                .padding(.horizontal, plan.gutter)
                .padding(.bottom, CicadaTheme.scaled(72))
        }
        .id(item.id)
        .focusable()
        .focusEffectDisabled()
        .onExitCommand { escape() }
        .focused($focus, equals: .detail)
    }

    // MARK: The lists' state

    private var inRun: Bool { run.mode != .browse }
    private var videoRows: [VideoRow] { VideoRunModel.rows(items: feedVM.items, states: videoCache.items) }
    private var searching: Bool { findOpen && !QuickMatch.tokens(feedVM.searchText).isEmpty }
    /// Every saved video, whatever Saved's View menu narrows to.
    private var videoItems: [MediaFeedItem] { feedVM.items.filter { FeedKind.of($0) == .video } }
    /// The saved videos find leaves, in the order drawn.
    private var visibleVideos: [MediaFeedItem] { feedVM.filteredItems.filter { FeedKind.of($0) == .video } }

    /// The rows ↑/↓ walk on a tab of saved items.
    private func listItems(_ tab: SleepTab) -> [MediaFeedItem] {
        switch tab {
        case .saved: feedVM.visible
        case .videos: visibleVideos
        case .waiting, .pastReads: []
        }
    }

    /// The live waiting count (H1): SSE-live when a snapshot has arrived, the loaded rows before.
    private var waitingCount: Int {
        Self.queueCount(status: store.status.value, fallback: sleepVM.queuedEpisodes.count)
    }

    /// Whether Waiting has anything to show: a queue, a parked conversation, the run's own block, or a queue that
    /// could not be read (an error is not "nothing waiting"). The person's-page note alone no longer keeps a
    /// "Waiting 0" tab up (owner 2026-10-16: a zero count hides its tab); it rides along whenever Waiting shows.
    private func waitingHasRows(_ page: SleepPageModel) -> Bool {
        if case .failed = page.queueLoad { return true }
        return waitingCount > 0 || page.parkedCount > 0 || showsRunBlock(page)
    }

    private var exportWaiting: Bool { !exportWaits.active(bank: store.bank).isEmpty }

    private func currentTab(_ page: SleepPageModel) -> SleepTab {
        SleepTab.resolve(chosen: chosenTab, waitingHasRows: waitingHasRows(page), saved: feedVM.items.count,
                         exportWaiting: exportWaiting, videos: videoItems.count)
    }

    /// The Waiting tab keeps its count everywhere (review of #363): the tab row is pinned, so once the room scrolls
    /// away it is the one place the waiting total is still on screen.
    private func tabRowTabs(_ page: SleepPageModel) -> [TextTab<SleepTab>] {
        SleepTabRow.tabs(SleepTab.visible(waitingHasRows: waitingHasRows(page), saved: feedVM.items.count,
                                          exportWaiting: exportWaiting, videos: videoItems.count),
                         waiting: waitingCount, saved: feedVM.items.count, videos: videoItems.count)
    }

    /// The detail column is open while the watch run is on, or while a saved item is open on a tab of saved items —
    /// never under Waiting or Past reads (a tab switch closes the item, `selectTab`).
    private func hasDetail(_ tab: SleepTab) -> Bool {
        inRun || (tab.hasFind && feedVM.openItem != nil)
    }

    // MARK: Paths (R-DL8, DR-28, DR-60)

    /// A tab is navigation: it closes the open item, the run and find, and never animates (DR-60, DR-61).
    private func selectTab(_ tab: SleepTab) {
        Instant.run {
            if inRun { run.leave() }
            if provenance.isPresented { provenance.close() }
            feedVM.columns.close()
            findOpen = false
            chosenTab = tab
        }
    }

    /// The root is the room over the tab its state chooses (`chosenTab == nil`): the watch run, the open item, the
    /// Reader and find all close, and the page scrolls back to the top.
    private func popToRoot() {
        appRouter.popToRoot(reduceMotion: reduceMotion) {
            if inRun { run.leave() }
            if provenance.isPresented { provenance.close() }
            feedVM.columns.close()
            findOpen = false
            chosenTab = nil
        }
        toTop &+= 1
        focus = .list
    }

    private func open(_ item: MediaFeedItem) {
        let change = {
            feedVM.columns.open(item.id)
            if provenance.isPresented { provenance.close() }
        }
        if feedVM.columns.openId == nil {
            withAnimation(CicadaMotion.columns(reduceMotion: reduceMotion)) { change() }
        } else {
            Instant.run { change() }
        }
        focus = .list
    }

    /// DR-68 — ↑/↓ open the neighbour in place on a tab of saved items; Waiting and Past reads have no row to open.
    private func move(_ delta: Int, in tab: SleepTab) {
        guard tab.hasFind else { return }
        Instant.run {
            guard let next = feedVM.columns.neighbour(delta, in: listItems(tab).map(\.id)) else { return }
            feedVM.columns.open(next)
            if provenance.isPresented { provenance.close() }
        }
        focus = .list
    }

    private func escape() {
        // DR-28 — in the run: the Reader first, then leave the run.
        if inRun {
            Instant.run { if provenance.isPresented { provenance.close() } else { run.leave() } }
            focus = .list
            return
        }
        Instant.run {
            switch feedVM.columns.escape(readerOpen: provenance.isPresented) {
            case .closeReader: provenance.close()
            case .closeDetail:
                feedVM.columns.close()
                focus = .list
            case .none: break
            }
        }
    }

    private func closeItem() {
        withAnimation(CicadaMotion.columns(reduceMotion: reduceMotion)) {
            provenance.close()
            feedVM.columns.close()
        }
        focus = .list
    }

    private func showList() {
        withAnimation(CicadaMotion.columns(reduceMotion: reduceMotion)) {
            if provenance.isPresented { provenance.close() } else { feedVM.columns.close() }
        }
    }

    /// G217 — one catalogue: the bare `+` / ⌘N opens the Sources page (where every way in is listed); a hand-off
    /// naming one tile still opens that tile's flow here, alone (`flowOnly`).
    private func openSheet(_ tile: AddSourceTile?) {
        guard let tile else {
            appRouter.routeToSources()
            return
        }
        sheetTile = tile
        showAddSheet = true
    }

    private func retryParked(_ ids: [String]?) {
        Task { @MainActor in
            await sleepVM.retryParked(ids: ids)
            await store.refresh([.status])
        }
    }

    // MARK: The watch run (G162)

    /// The Videos strip's *Choose videos…*: the picker, or the run's progress while a hand-off still has videos to
    /// record.
    private func beginRun() {
        Instant.run {
            if provenance.isPresented { provenance.close() }
            feedVM.columns.close()
            findOpen = false
            run.begin(summary: videoCache.summary)
        }
        focus = .list
    }

    private func leaveRun() {
        Instant.run { run.leave() }
        focus = .list
    }

    // MARK: Hand-offs (each consumer reads then clears, so a second firing is a no-op)

    private func consumePendingAddSource() {
        guard let tile = appRouter.consumeAddSource() else { return }
        openSheet(tile)
    }

    /// R-DL16 / DR-30 — a landed item opens in Saved, every kind shown, scrolled into view; a keyboard-free path, so
    /// it never animates.
    private func consumeLanding() {
        guard let id = appRouter.consumeSavedItem() else { return }
        Instant.run {
            if inRun { run.leave() }
            findOpen = false
            chosenTab = .saved
            if feedVM.land(mediaEntityId: id) { landingToken &+= 1 }
        }
    }

    /// Anything that asks for the video picker: the Videos tab with the picker open.
    private func consumeVideoChooser() {
        guard appRouter.consumeVideoChooser() else { return }
        Instant.run {
            chosenTab = .videos
            if provenance.isPresented { provenance.close() }
            feedVM.columns.close()
            findOpen = false
            run.beginChoosing()
        }
        Task { await videoCache.refresh() }
    }

    /// Track Z Z1 — the page, resolved once per body (§9). Every reader below
    /// takes its numbers from this value, so the room, the queue and the
    /// controls cannot disagree about which reading they show (H1, now
    /// structural). `now` is the body's own clock read — `studyRows` ages and
    /// the 6 s digest window already depended on it.
    /// What moves Waiting's per-conversation rows: the batch, what is filed and parked, and the paused run —
    /// never a tick (M3).
    private var queueKey: String {
        let drain = sleepVM.status?.drain
        return [drain?.id ?? "", "\(drain?.batch ?? 0)", "\(drain?.filed ?? 0)", "\(drain?.parked ?? 0)",
                "\(store.sleepEvent?.parkedCount ?? 0)", sleepVM.pausedRun?.runId ?? ""].joined(separator: "|")
    }

    private func resolvePage(now: Date = .now) -> SleepPageModel {
        SleepPageModel.resolve(
            status: sleepVM.status, sse: store.sleepEvent, queued: sleepVM.queuedEpisodes,
            schedule: sleepVM.schedule,
            enginePreview: SleepEnginePreviewSource.current(chooser: engineVM.response, page: sleepVM.enginePreview),
            history: sleepVM.history,
            storeStatus: store.status.value,
            queueLoad: StudyListCard.loadState(status: store.status.value,
                                               isLoading: store.status.isEmpty && store.status.isRefreshing,
                                               error: store.domainErrors[.status]),
            justFinishedAt: justFinishedAt, intakeInFlight: store.intakeInFlight,
            paused: sleepVM.pausedRun, batchSize: sleepVM.batchSize, pausing: sleepVM.isCancelling, now: now)
    }

    /// The one error the page has to tell, if there is one — `lastError`
    /// preferred over the transient `errorMessage`, which is how the page has
    /// always resolved it.
    ///
    /// This drives Past reads › Last cycle and nothing else. It is deliberately NOT what
    /// `liveness` reads: `errorMessage` is a *fetch* failure, which a stopped
    /// backend raises constantly, so it says "we could not reach it" — the
    /// same fact the chip is there to state — rather than "a cycle failed".
    private var pageError: String? {
        guard let error = sleepVM.lastError ?? sleepVM.errorMessage, !error.isEmpty else { return nil }
        return error
    }

    /// R-A12. Both domains this page projects are asked when the BACKEND last
    /// confirmed them (`Snapshot.refreshedAt`, not `loadedAt` — review round
    /// 2: a disk hydrate moves `loadedAt`, so reading it dated a cold launch
    /// against a dead backend by the launch minute); `stalestRefreshedAt`
    /// takes the older of the two, so the chip never dates the page by its
    /// freshest card, and returns nil — no chip — while neither has ever been
    /// confirmed.
    ///
    /// **`isError` is the CYCLE's error, not the page's** (review round 1).
    /// `pageError` folds in `sleepVM.errorMessage`, which a stopped backend
    /// sets on every `load()` — routing that here made a disconnected page
    /// report itself `.live`, i.e. killed the feature in the one state it was
    /// built for. `lastError` is `status?.error`: a cycle that actually
    /// failed, which is real news and stays at full contrast. `pageError`
    /// keeps its one job — driving Past reads › Last cycle's error rows, which
    /// `SleepPastReads` places outside every desaturated group.
    ///
    /// `now` is left at its default, which is read fresh on every body
    /// evaluation — that is what lets `SleepLiveness.staleAfter` do its work
    /// (final review, finding 1). It is deliberately NOT the R8 case: R8 bans
    /// the wall clock from `sleepBubbleText` because prose that flickers
    /// between renders is a lie about *state*; here the elapsed time since the
    /// last backend answer IS the state being reported.
    private var liveness: SleepLiveness {
        sleepLiveness(
            isConnected: store.isConnected,
            refreshedAt: SleepLiveness.stalestRefreshedAt(store.status.refreshedAt,
                                                          store.sourcesOverview.refreshedAt),
            isError: sleepVM.lastError != nil
        )
    }

    // MARK: The lists' doors (Track Z Z3's tail links, now tabs)

    /// A tail link, a spine or a hand-off names an old Details section: select the tab that holds it now (DESIGN
    /// §3.6) and bring the tab row to the top — with anything open closed first, so the list is on screen.
    private func openDetails(_ section: DetailsSection) {
        selectTab(SleepTab.holding(section))
        scrollToTabs = true
    }

    private func consumeDetailsRoute() {
        if let section = appRouter.consumeSleepDetails() { openDetails(section) }
    }

    /// PR #19 round-4 review: a single `sleepVM.load()` was fired per live
    /// count change with no follow-up. `load()` swallows its own per-fetch
    /// errors into `sleepVM.errorMessage` rather than throwing (each of
    /// status/episodes/schedule is caught independently), so a failed
    /// episodes fetch never surfaced as a thrown error here — it just left
    /// `sleepVM.queuedEpisodes` stale. And even on a clean fetch, the
    /// returned rows can still disagree with the live count (a Sleep cycle
    /// racing the fetch). Either way, if the live count doesn't move again,
    /// `.onChange` above never re-fires and the header/rows stay
    /// inconsistent for as long as the page is open. This loop re-checks
    /// `queueNeedsReconcile` after every attempt and retries with bounded
    /// backoff instead of giving up silently after one try — bounded so a
    /// persistent mismatch (a real bug, not a transient blip) cannot turn
    /// into an unbounded request loop; `queueNeedsReconcile` itself stays
    /// visible (the header and rows keep disagreeing) rather than being
    /// papered over.
    private func runReconcile() async {
        var attempt = 0
        while !Task.isCancelled {
            await sleepVM.load()
            guard !Task.isCancelled else { return }
            let stillNeedsReconcile = Self.queueNeedsReconcile(
                liveUnprocessed: store.status.value?.episodes.unprocessed,
                loadedQueuedCount: sleepVM.queuedEpisodes.count)
            guard Self.shouldRetryReconcile(attempt: attempt, stillNeedsReconcile: stillNeedsReconcile) else { return }
            attempt += 1
            try? await Task.sleep(for: Self.reconcileBackoff(attempt: attempt))
        }
    }

    /// Reconcile retry policy, pulled out as pure functions (mirrors
    /// `queueCount`/`queueNeedsReconcile` above) so the bound and the backoff
    /// curve are unit-testable without standing up a view or a live Task loop.
    static let maxReconcileAttempts = 3

    /// What reruns the page's load task: the Store's newest Sleep time and whether Sleep is running.
    private var refreshKey: String {
        "\(store.status.value?.lastSleepAt ?? "")|\(store.status.value?.sleep.status ?? "")"
    }

    static func shouldRetryReconcile(attempt: Int, stillNeedsReconcile: Bool) -> Bool {
        stillNeedsReconcile && attempt < maxReconcileAttempts
    }

    static func reconcileBackoff(attempt: Int) -> Duration {
        .seconds(min(8, 1 << attempt))
    }

    /// The count the page's lists must agree with (H1): SSE-live
    /// `store.status.episodes.unprocessed` when a snapshot has arrived,
    /// falling back to the once-per-visit `sleepVM.queuedEpisodes` count
    /// before the first one does. Pulled out as a pure function so the
    /// precedence is unit-testable without standing up a view.
    static func queueCount(status: StatusSnapshot?, fallback: Int) -> Int {
        status?.episodes.unprocessed ?? fallback
    }

    /// Whether the SSE-live unprocessed count has drifted from the rows
    /// `sleepVM.queuedEpisodes` is currently showing — the signal that owes
    /// the page a refetch (H1 follow-up, PR #19 review). `nil` (no status
    /// snapshot yet) never triggers a reconcile — `queueCount` already falls
    /// back to `loadedQueuedCount` in that case, so there is nothing to
    /// disagree with. Pulled out as a pure function, mirroring `queueCount`
    /// above, so the trigger condition is unit-testable without a view.
    static func queueNeedsReconcile(liveUnprocessed: Int?, loadedQueuedCount: Int) -> Bool {
        guard let liveUnprocessed else { return false }
        return liveUnprocessed != loadedQueuedCount
    }

    // MARK: History disclosure (G125 R12)

    /// A second click on an already-expanded row just closes it — no
    /// re-fetch. `loadDetail` itself is the cache-hit guard for the OPEN
    /// case: a row that's been opened once before never asks the network
    /// again this session.
    private func toggleHistory(_ commit: String) {
        let opening = sleepVM.expanded != commit
        // One card open at a time; a click eases open, a key opens in one frame (DR-60, `RunCardMotion`).
        withAnimation(RunCardMotion.animation(eventType: NSApp.currentEvent?.type, reduceMotion: reduceMotion)) {
            sleepVM.expanded = opening ? commit : nil
            if opening { sleepVM.expandedRun = nil }
        }
        if opening {
            Task { @MainActor in await sleepVM.loadDetail(commit) }
        }
    }

    /// A run's card: the same one-open rule and motion as a cycle's; its detail (models, batches) loads beside its items.
    private func toggleRun(_ id: String) {
        let opening = sleepVM.expandedRun != id
        withAnimation(RunCardMotion.animation(eventType: NSApp.currentEvent?.type, reduceMotion: reduceMotion)) {
            sleepVM.expandedRun = opening ? id : nil
            if opening { sleepVM.expanded = nil }
        }
        if opening {
            Task { @MainActor in await sleepVM.loadRunDetail(id) }
        }
    }

    /// R-Z12 — one of the page's two beats not caused by input, and it has a
    /// fact behind it: the new commit. The one helper both completion
    /// observers call (the end edge and a later history change, Task 8
    /// review r1), so the cheer and its announcement can never diverge. The
    /// §6.4 matrix decides whether the mood may cheer now (`.digesting` /
    /// `.happy`); a history that lands after the 6 s digest still sets the
    /// link, silently. The announcement is the cheer's text twin (§11).
    private func celebrateCompletion() {
        room.play(.cheer, state: resolvePage().mood, reduceMotion: reduceMotion)
        AccessibilityNotification.Announcement(Copy.sleepFinished).post()
    }

    /// T7 / I17 — Past reads, the cycle's history row expanded (its detail
    /// loads through the one cached path, `toggleHistory` → `loadDetail`).
    /// The link clears as it is followed: what changed is now on screen, so
    /// the sentence goes back to the state.
    private func showWhatChanged() {
        guard let commit = room.followWhatChanged() else { return }
        if sleepVM.expanded != commit { toggleHistory(commit) }
        openDetails(.pastNights)
    }

    // MARK: The staleness chip

    /// "as of 16:12" — the moment the numbers below were last confirmed by a
    /// backend that is no longer answering. A dated page is honest; a blank
    /// one loses work the reader can still use, and an undated one lies by
    /// omission.
    private func stalenessChip(_ asOf: Date) -> some View {
        HStack(spacing: CicadaTheme.spacingXS) {
            Image(systemName: "wifi.slash")
                .font(CicadaTheme.font(size: 9, weight: .semibold))
            Text(Copy.asOf(asOf))
                .font(CicadaTheme.font(size: 10, weight: .semibold))
        }
        .foregroundStyle(CicadaTheme.textTertiary)
        .padding(.horizontal, CicadaTheme.spacingSM)
        .padding(.vertical, 3)
        .background(CicadaTheme.surfaceElevated)
        .clipShape(Capsule())
        .help(Copy.notConnectedExplainer)
        // Collapse FIRST, then label — the folder's house pattern
        // (`SleepHero`, `BookPile` and `SleepStageStrip` all do this). Without it SwiftUI propagates the
        // container's label to each child and VoiceOver reads the whole
        // sentence twice, once for the glyph and once for the text.
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(Copy.notConnectedExplainer) \(Copy.asOf(asOf))")
    }

    // MARK: The room (G106 amendment; G107 art; G125 the study desk; the Sleep redesign)

    /// The study room, out of its card (DESIGN §3.2): the art sits on the page ground at a whole number of points
    /// per cell — 5, 4 or 3, a step function of the column's width (`SleepLayout.artScale`), so a pixel is never
    /// resampled (ruling R3) — with its floor fading into the page (a mask on the art, no shadow, DR-9/10). Under it,
    /// never over it (DR-13), the room's three lines in the 760 pt text column (DR-36): the sentence, the one control,
    /// the whisper.
    ///
    /// Every value it draws comes from `page` (Track Z Z1), which resolved the
    /// SSE-over-REST precedence (`store.sleepEvent` first, the last
    /// `/sleep/status` fetch second) once for the whole body.
    ///
    /// The scene box is a FIXED height at a given width step (R-A2), so idle →
    /// running → idle never reflows the art: the mood changes the worm's
    /// frames, never the room's geometry.
    ///
    /// Track Z Z2 (R-Z5): the worm speaks in one fixed slot directly under it — the display-face sentence — then
    /// the one control and the whisper line, all centred on the room. The strip stays, but only with news, and at
    /// the block's last row (Z-P9) so neither the sentence nor the control the person just pressed moves when it
    /// appears.
    private func roomBlock(_ page: SleepPageModel, columnWidth: CGFloat) -> some View {
        // One reading feeds the status line AND the answers (Task 6), so the
        // worm can never answer from a different snapshot than it states.
        let context = page.roomContext(recentCycleCommit: room.recentCycleCommit)
        let status = roomSentence(context)
        let answers = wormAnswers(context)
        let cell = SleepLayout.artScale(columnWidth: min(columnWidth, SleepLayout.artMaxWidth))

        return VStack(alignment: .center, spacing: CicadaTheme.spacingMD) {
            // Track Z Z5 (R-Z8): the room is its own view — the inert art,
            // the worm on its lattice, the real pile, and a hotspot layer
            // derived from the same pure layout. The bracket line (P8) moved
            // from this group's label onto the worm's own element as its value.
            StudyRoom(page: page, statusLine: status, answers: answers, room: room,
                      episodes: sleepVM.queuedEpisodes, onOpenDetails: openDetails,
                      onWhatChanged: room.recentCycleCommit == nil ? nil : { showWhatChanged() },
                      reachable: liveness == .live, cell: cell)
                .accessibilitySortPriority(RoomA11yOrder.room)

            // G212 — each machine by its own name, how it connects and what waits; a click opens its queue below.
            MachinesStripView(machines: sleepVM.machines, selected: openMachine) { machine in
                Instant.run {
                    openMachine = machine?.id
                    if machine != nil { selectTab(.waiting) }
                }
            }

            // Everything under the room, one centred group in the 760 pt column (2026-10-16).
            SleepRoomColumn(page: page, status: status, answers: answers, room: room,
                            feedAsleep: feedIsAsleep(page.mood),
                            perform: { action in
                                switch action {
                                case .retry: Task { await store.refresh([.status]) }
                                case .openDetails(let section): openDetails(section)
                                case .openInbox: selectedTab = .inbox
                                // Z-P25 — the sentence names the lamp, so the
                                // popover points at the lamp, not the whisper line.
                                case .openLamp: room.lampPopover = .lamp
                                case .whatChanged: showWhatChanged()
                                }
                            },
                            ownerEntityId: ownerEntityId, onSelectEntity: onSelectEntity,
                            openDetails: openDetails)
        }
        .accessibilityElement(children: .contain)
        .frame(maxWidth: .infinity)
    }

    /// Sleep page v5 (A7) — the run whose detail the lists read: the running or finished drain, else the paused run.
    private var detailRunId: String? {
        if let drain = sleepVM.status?.drain, !drain.active, drain.byOrigin != nil { return drain.id }
        return sleepVM.pausedRun?.runId
    }

    /// What moves when the detail run's numbers do (`SleepViewModel.runDetailFreshness`).
    private var detailRunFreshness: String {
        SleepViewModel.runDetailFreshness(drain: sleepVM.status?.drain, paused: sleepVM.pausedRun)
    }

    /// Last cycle's run rows (`LastCycleRow.runRows`): the drain, the paused run, the run's own numbers from history
    /// and its detail, parked conversations, a scheduled run's spend words, and the reserve's figure (Past reads is
    /// one of ruling 12's two homes for it).
    private func runRows(_ page: SleepPageModel) -> [LastCycleRow] {
        let drain = page.drain
        let runId = drain?.id ?? page.paused?.runId
        let run = runId.flatMap { id in sleepVM.history.first { $0.drainId == id }?.run }
        let preview = SleepEnginePreviewSource.current(chooser: engineVM.response, page: sleepVM.enginePreview)
        let reserve = EngineQuickMenuModel.Reserve.from(engineVM.response?.reserve, billing: preview?.manual.billing)
        let detail = runId.flatMap { sleepVM.runDetails[$0] }
        let summary = runId.flatMap { id in sleepVM.history.first { $0.drainId == id }?.usageSummary }
        // How THIS run was billed, from its own usage; only a run still reading, with nothing measured yet, reads
        // the scheduled preview — the engine it is running on right now.
        let billing = LastCycleRow.runBilling(usage: detail?.usage, summary: summary)
            ?? (drain?.active == true ? preview?.scheduled.billing : nil)
        return LastCycleRow.runRows(drain: drain, paused: page.paused, run: run, detail: detail,
                                    parkedCount: page.parkedCount, runBilling: billing,
                                    reserveValue: reserve?.pct != nil ? reserve?.value : nil)
    }

    /// The run's part of Waiting shows while a run reads in batches or waits paused.
    private func showsRunBlock(_ page: SleepPageModel) -> Bool {
        guard page.drain?.byOrigin != nil else { return false }
        return (page.isRunning && page.drain?.active == true) || page.paused != nil
    }

    /// "Your own page is ready" — a memory never consolidated, whose owner page the graph already holds (A10).
    private func ownerReady(_ page: SleepPageModel) -> Bool {
        page.debt?.hasRunBefore == false && !page.isRunning && ownerEntityId != nil
    }

    /// The owner's page (G117), from the graph snapshot — `nil` until it has loaded (never a guess).
    private var ownerEntityId: String? {
        store.graph.value?.nodes.first { $0.isOwner }?.id
    }
}

/// 2026-10-16 — the Sleep page's refetch when the Store's newest Sleep time moves. A drain moves it every batch, so
/// while a run reads the page refetches at most once per `interval`; with no run reading (a visit, or the run ending
/// as Sleep's state flips) it always refetches. Pure, so `LastCycleFiguresTests` holds it.
enum SleepPageRefresh {
    static let interval: TimeInterval = 30

    static func shouldRefetch(running: Bool, last: Date?, now: Date) -> Bool {
        guard running, let last else { return true }
        return now.timeIntervalSince(last) >= interval
    }
}
