import SwiftUI

// MARK: - The page's arrangement (G125 v3 Task 7)

/// How the Sleep page lays itself out at a given width — a value, so the
/// reflow boundary is a named constant a test can assert rather than a `>`
/// buried in a `body`.
///
/// `maxContentWidth` is part of the layout for a reason: the page pinned a
/// literal `.frame(maxWidth: 760)`, which no two-column arrangement can fit
/// inside. Below the boundary the stacked page keeps exactly that 760 pt
/// column — unchanged behaviour on a small window — and above it the cap opens
/// far enough that the LEFT column alone is still about as wide as the old
/// single column, so the hero and the room do not reflow when the second
/// column appears.
struct SleepLayout: Equatable {
    let isTwoColumn: Bool
    let maxContentWidth: CGFloat
    /// The left column's share of the content width; `1.0` when stacked, so a
    /// caller can multiply unconditionally.
    let leftFraction: Double

    /// Inclusive: at exactly this width the page is already two columns.
    static let twoColumnMinWidth: CGFloat = 1000
    static let stackedContentWidth: CGFloat = 760
    /// 2/3 of this is ~773 pt — the width the single column has always had.
    static let twoColumnContentWidth: CGFloat = 1160
    static let twoColumnLeftFraction: Double = 2.0 / 3.0

    /// The left column's width inside `available`, after the page's own
    /// padding and the gutter between the columns. `nil` when stacked: there is
    /// one column and it takes the whole width.
    func leftColumnWidth(available: CGFloat, padding: CGFloat, gutter: CGFloat) -> CGFloat? {
        guard isTwoColumn else { return nil }
        let content = min(available, maxContentWidth) - padding * 2 - gutter
        return max(0, content) * leftFraction
    }
}

/// A width of zero arrives on a window's first layout pass; it stacks, because
/// a two-column split of nothing would divide a zero.
func sleepLayout(width: CGFloat) -> SleepLayout {
    guard width >= SleepLayout.twoColumnMinWidth else {
        return SleepLayout(isTwoColumn: false,
                           maxContentWidth: SleepLayout.stackedContentWidth,
                           leftFraction: 1.0)
    }
    return SleepLayout(isTwoColumn: true,
                       maxContentWidth: SleepLayout.twoColumnContentWidth,
                       leftFraction: SleepLayout.twoColumnLeftFraction)
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
///   banner's own contrast is not this function's job: `leftColumn` keeps
///   `errorBanner` outside every `.saturation` group, so both errors render at
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

// MARK: - Sleep Dashboard — the study desk (G125)

/// **The motion budget (G125 v3 Task 8, spec R-A13).** Four rules, and every
/// one of them has a test or a lint behind it — a budget that lives only in a
/// comment is a budget that drifts:
///
/// 1. **Idle is still.** Nothing on a settled page moves except the worm's own
///    frame loop. `DeskSceneView` has no `TimelineView` (its docstring says
///    so), and `SleepStageStrip` starts one *only* while a pip is actually
///    active — an idle page costs zero redraws.
/// 2. **Nothing animates longer than 400 ms**, except the stage pulse, which
///    is capped separately at 1.2 s (`SleepStages.pulsePeriod`) because a
///    breath is a state indicator, not a transition. Every duration on this
///    page is a named constant on `SleepMotion`, and
///    `SleepNumbersLintTests.testTheSleepFolderDeclaresNoLiteralAnimationDuration`
///    fails the build on a literal `duration:` anywhere else under
///    `Views/Sleep/`.
/// 3. **Reduce Motion holds every animation at its terminal frame.** The worm
///    through `BookwormView.frameIndex(…reduceMotion:)`, the pulse through
///    `stagePulse(at:reduceMotion:)`, and every value-driven settle through
///    `SleepMotion.settle/pile/disclosure(reduceMotion:)`, which return `nil`
///    — SwiftUI for "jump to the new value".
/// 4. **No spinner where a real count exists.** A `ProgressView` on this page
///    appears only where there is genuinely nothing to count yet: the queue
///    before its first fetch, a history row's detail mid-load, and the
///    Consolidate/Cancel buttons' own in-flight state. The queue's rows lost
///    theirs in Task 6 — they have `read of total`.
struct SleepView: View {
    @Binding var selectedTab: AppTab
    /// Entity chips inside the consolidation history's expanded detail land
    /// here (mirrors `SourcesPageView`'s own closure at `ContentView.swift`)
    /// — jump to Graph and open the card, exactly like an Ask citation.
    var onSelectEntity: ((String) -> Void)?

    @Environment(SleepViewModel.self) private var sleepVM
    // H1: the study list's header and the desk card's bubble/pile must agree
    // on one live reading of the queue. `Store.status`/`Store.sleepEvent` are
    // the SSE-live sources; reading them here (instead of only
    // `sleepVM.queuedEpisodes.count`, fetched once per visit) keeps every
    // readout on the page from disagreeing when a capture lands while it's
    // open.
    @Environment(Store.self) private var store
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var loadedOnce: Bool = false
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

    /// G125 Task 7 — the SSE-preferred, REST-fallback read of the cycle's
    /// per-origin queue/read dicts (R3) that both the desk card's book pile
    /// and the study list are built from. Resolved once per body evaluation
    /// so the two never disagree about which cycle's counts they're showing.
    private var liveOriginCounts: (queueByOrigin: [String: Int], readByOrigin: [String: Int]) {
        resolveOriginCounts(sse: store.sleepEvent, status: sleepVM.status)
    }

    private var studyListRows: [StudyRow] {
        let origins = liveOriginCounts
        return studyRows(
            queued: sleepVM.queuedEpisodes,
            queueByOrigin: origins.queueByOrigin,
            readByOrigin: origins.readByOrigin,
            running: sleepVM.isRunning
        )
    }

    var body: some View {
        ZStack {
            // No .ignoresSafeArea(): the title bar is darkened at the window level
            // (CicadaApp). Ignoring the safe area here pushed content under the menu
            // bar and stretched the window to full screen height.
            CicadaTheme.background

            // The page asks its own width what arrangement it is in, once, and
            // hands the answer down (`sleepLayout`). The GeometryReader wraps
            // the ScrollView rather than sitting inside it: inside, it would
            // measure the scroll content it is itself sizing.
            GeometryReader { geo in
                scrollContent(width: geo.size.width, layout: sleepLayout(width: geo.size.width))
            }

            // Top-right: just the `?` button now (R10 — the Sleep/Upload
            // pair left this page; the one Consolidate control lives in the
            // study list's footer). It opens *How Cicada sleeps* instead of
            // the generic "About these actions" popover every other page
            // shows.
            VStack {
                HStack {
                    Spacer()
                    TopBarControls(
                        selectedTab: $selectedTab,
                        showUploadOverlay: .constant(false),
                        showsSleep: false,
                        showsUpload: false,
                        help: .howSleepWorks
                    )
                    .padding(CicadaTheme.spacingLG)
                }
                Spacer()
            }
        }
        .task {
            if !loadedOnce {
                loadedOnce = true
                await sleepVM.load()
            }
        }
        // G106 amendment: this view's own edge-detection for the mood
        // card's `.digesting` window — see `justFinishedAt`'s declaration
        // for why this can't reuse `SleepViewModel.onCycleCompleted` or
        // `Store.onStatus`.
        .onChange(of: sleepVM.status?.status) { oldValue, newValue in
            if oldValue == "running" && newValue == "idle" {
                justFinishedAt = Date()
            }
        }
        // PR #19 review: the study list's header reads SSE-live `store.status`
        // while its rows stay pinned to whatever `sleepVM.load()` last
        // fetched, once per visit. A capture (or another Sleep cycle
        // finishing elsewhere) bumps the live count without touching the
        // rows, so the two contradict each other for as long as the page
        // stays open. One freshness model: whenever the live unprocessed
        // count disagrees with the loaded rows, refetch.
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

    // MARK: Composition — two columns above 1000 pt, stacked below (Task 7)

    /// The scrolling body. Two columns side by side when there is room; the
    /// SAME two groups stacked when there is not, in the same order — a reflow
    /// must never reorder what the reader was looking at.
    private func scrollContent(width: CGFloat, layout: SleepLayout) -> some View {
        let leftWidth = layout.leftColumnWidth(available: width,
                                               padding: CicadaTheme.spacingXL,
                                               gutter: CicadaTheme.spacingLG)
        return ScrollView {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                headerRow
                if layout.isTwoColumn {
                    HStack(alignment: .top, spacing: CicadaTheme.spacingLG) {
                        leftColumn.frame(width: leftWidth)
                        rightColumn
                    }
                } else {
                    leftColumn
                    rightColumn
                }
            }
            .padding(CicadaTheme.spacingXL)
            .frame(maxWidth: layout.maxContentWidth)
            .frame(maxWidth: .infinity, alignment: .top)
        }
    }

    /// The one error the page has to tell, if there is one — `lastError`
    /// preferred over the transient `errorMessage`, which is how `leftColumn`
    /// has always resolved it.
    ///
    /// This drives `errorBanner` and nothing else. It is deliberately NOT what
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
    /// keeps its one job — driving `errorBanner`, which `leftColumn` already
    /// places outside every desaturated group.
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

    /// The page's subject: the room, what the cycle is doing, and what is
    /// waiting for it. The error banner keeps its place between the two — it is
    /// news about the cycle the desk card is describing.
    ///
    /// R-A12: the desaturation is applied **per card**, not to the column, so
    /// the error banner sits at full contrast between two dimmed cards. A
    /// group modifier here would be one character shorter and would take the
    /// banner down with it.
    ///
    /// `.saturation` is applied UNCONDITIONALLY, at the identity value 1.0
    /// while live, and that is deliberate (review round 1 asked for a
    /// conditional). Wrapping it in an `if` produces a `_ConditionalContent`,
    /// and switching branches is a change of structural identity: SwiftUI
    /// tears down and rebuilds the subtree, so `StudyListCard`'s
    /// `@State expandedOrigins` would empty itself every time the connection
    /// flaps — the reader loses the rows they just opened at the exact moment
    /// the page is trying to tell them something. That is the same class of
    /// bug as the `.id()` remounts the View-menu work (G130) was written to
    /// avoid. The conditional would also not remove the filter from the
    /// pixel art in the state that matters — a stale page still filters
    /// `deskCard` either way — so the crispness question is a live-render
    /// check (it is on the verification list), not a code-shape one.
    @ViewBuilder
    private var leftColumn: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            deskCard
                .saturation(liveness.saturation)
            if let error = pageError {
                errorBanner(error)
            }
            StudyListCard(rows: studyListRows, episodes: sleepVM.queuedEpisodes, onSelectEntity: onSelectEntity)
                .saturation(liveness.saturation)
        }
    }

    /// The page's margin: where memory came from, and what past cycles did with
    /// it. Both are projections of domains the caller already holds — neither
    /// card fetches anything (R-A10). Nothing here is news, so the whole
    /// column takes the liveness treatment together.
    private var rightColumn: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            MemorySourcesCard(rows: memoryRows) { selectedTab = .sources }
            ConsolidationHistoryCard(
                entries: sleepVM.history,
                details: sleepVM.details,
                expanded: sleepVM.expanded,
                onToggle: toggleHistory,
                onSelectEntity: onSelectEntity
            )
        }
        .saturation(liveness.saturation)
    }

    /// A projection of `store.sourcesOverview` — the SAME domain the hero's
    /// "N sources feeding it" tile counts, read once more rather than fetched
    /// again (R-A10: no new endpoint, no new freshness model).
    ///
    /// `Date()` is read here because the activity window has to start
    /// somewhere; it moves once a day, which is the only granularity the UTC
    /// day keys have. That is not the R8 clock-flicker case the speech bubble
    /// forbids — nothing here changes between two renders a second apart.
    private var memoryRows: [MemorySourceRow] {
        memorySourceRows(overview: store.sourcesOverview.value ?? [], today: Date())
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
    /// The one requested point size for the whole hero. `BookwormView` and
    /// `deskSceneLayout` each snap it the same way (G130 R6), so passing this
    /// single number to both is what puts the room and the character on one
    /// lattice — P12: two pixel scales in one picture read as a bug.
    static let wormPointSize: CGFloat = 120

    static let maxReconcileAttempts = 3

    static func shouldRetryReconcile(attempt: Int, stillNeedsReconcile: Bool) -> Bool {
        stillNeedsReconcile && attempt < maxReconcileAttempts
    }

    static func reconcileBackoff(attempt: Int) -> Duration {
        .seconds(min(8, 1 << attempt))
    }

    /// The count `StudyListCard`'s content must agree with (H1): SSE-live
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
        withAnimation(SleepMotion.disclosure(reduceMotion: reduceMotion)) {
            sleepVM.expanded = opening ? commit : nil
        }
        if opening {
            Task { @MainActor in await sleepVM.loadDetail(commit) }
        }
    }

    // MARK: Header

    private var headerRow: some View {
        // SleepView's scroll content already carries `spacingXL` padding around
        // the whole VStack, so this header strips PageHeader's outer padding and
        // just reuses its title/subtitle typography for visual parity.
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            HStack(spacing: CicadaTheme.spacingSM) {
                Text("Sleep Cycle")
                    .font(CicadaTheme.titleFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                // R-A12: the chip is the *explanation* for the dimming below
                // it, so it stays at full contrast and sits outside every
                // desaturated group.
                if let asOf = liveness.asOf {
                    stalenessChip(asOf)
                }
                Spacer(minLength: 0)
            }
            Text(Copy.sleepSubtitle)
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textSecondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    /// "as of 16:12" — the moment the numbers below were last confirmed by a
    /// backend that is no longer answering. A dated page is honest; a blank
    /// one loses work the reader can still use, and an undated one lies by
    /// omission.
    private func stalenessChip(_ asOf: Date) -> some View {
        HStack(spacing: 4) {
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
        // (`SleepHero`, `BookPile`, `SleepStageStrip`, `SleepBubble`,
        // `MemorySourcesCard` all do this). Without it SwiftUI propagates the
        // container's label to each child and VoiceOver reads the whole
        // sentence twice, once for the glyph and once for the text.
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(Copy.notConnectedExplainer) \(Copy.asOf(asOf))")
    }

    // MARK: The desk (G106 amendment; G107 art; G125 the study desk)

    /// The mascot card, now "the study room" (G125 v3 Task 3): the speech
    /// bubble over a night window, a floor lamp, a plant, a cushion and a mug,
    /// with the 24×24 colour bookworm (G107) sitting on the cushion at 120 pt
    /// — five whole cells per point-row, so the pixels stay crisp (ruling R3)
    /// — and the REAL `BookPileView` standing in the column
    /// `deskSceneLayout` reserves for it beside him. Nothing in the room is
    /// painted books (P10): the page's one volume encoding is that pile.
    ///
    /// Both the mood and the per-origin counts prefer the
    /// continuously-updating SSE `sleep` event (`store.sleepEvent`) and fall
    /// back to the last REST `/sleep/status` fetch, via
    /// `resolveSleepDebt`/`resolveProgressPct`/`resolveOriginCounts`.
    ///
    /// The scene box is a FIXED height at a given zoom (R-A2), so idle →
    /// running → idle never reflows the art: the mood changes the worm's
    /// frames, never the room's geometry.
    private var deskCard: some View {
        let debt = resolveSleepDebt(sse: store.sleepEvent, status: sleepVM.status)
        let mood = deriveSleepPageMood(
            status: sleepVM.status, debt: debt, justFinishedAt: justFinishedAt,
            intakeInFlight: store.intakeInFlight
        )
        let origins = liveOriginCounts
        let rows = studyListRows
        let books = bookPileLayout(originVolumes(
            queued: sleepVM.queuedEpisodes,
            queueByOrigin: origins.queueByOrigin,
            readByOrigin: origins.readByOrigin,
            running: sleepVM.isRunning
        ))
        let bubbleCtx = BubbleContext(
            unprocessed: debt?.unprocessedCount ?? 0,
            topOriginLabel: rows.first?.label,
            topOriginCount: rows.first?.count ?? 0,
            stage: sleepVM.status?.stage ?? 0,
            read: origins.readByOrigin.values.reduce(0, +),
            total: origins.queueByOrigin.values.reduce(0, +),
            hoursSinceLastCycle: debt?.hoursSinceLastCycle
        )

        let scene = deskSceneLayout(pointSize: Self.wormPointSize)

        return VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            SpeechBubbleView(text: sleepBubbleText(mood, bubbleCtx))

            ZStack(alignment: .bottomLeading) {
                // R-A3: lit exactly when Sleep is scheduled. `enabled` is
                // `mode != "manual"` by definition (`ScheduleConfig`), so the
                // lamp and the schedule sentence read the same field — the
                // art can never disagree with the words.
                DeskSceneView(pointSize: Self.wormPointSize, lampLit: sleepVM.schedule.enabled)

                // The worm sits on the cushion; `caption` is dropped because
                // the scene positions the sprite by its own box, and a
                // VStack'd caption underneath would move it off the cushion.
                // The bracket line survives as this group's VoiceOver label
                // below — the sprite loses its visible caption, not its
                // meaning (P8).
                BookwormView(state: mood, pointSize: Self.wormPointSize, caption: nil)
                    .offset(x: scene.wormOrigin.x, y: -scene.wormOrigin.y)

                // The REAL pile, in the column the layout reserves for it —
                // never a painted stack (P10).
                BookPileView(books: books)
                    .frame(width: scene.pileFrame.width, height: scene.pileFrame.height,
                           alignment: .bottomLeading)
                    .offset(x: scene.pileFrame.minX, y: -scene.pileFrame.minY)
            }
            .frame(width: scene.size.width, height: scene.size.height, alignment: .bottomLeading)
            .accessibilityElement(children: .contain)
            .accessibilityLabel(sleepDebtBracketText(mood, debt: debt))

            // R-A4…R-A7 — the promoted count, the meter that names its noun,
            // the three measured tiles and the page's one Consolidate/Cancel
            // control. Every number it draws is resolved ABOVE, once per body
            // evaluation (H1), and handed down: the hero can never disagree
            // with the book pile or the queue card about which cycle's counts
            // it is showing.
            SleepHeroView(
                mood: mood,
                debt: debt,
                read: bubbleCtx.read,
                total: bubbleCtx.total,
                queuedCount: sleepVM.queuedEpisodes.count
            )

            // R-A8 — the five-stage strip, in the slot the old
            // `Text("Stage N of 5")` + bare `ProgressView` pair occupied.
            // Every input is the SAME reading the hero and the book pile got
            // (H1): the stage from the one status snapshot, the two counts
            // from the one `resolveOriginCounts` call above.
            SleepStageStrip(
                pips: stageStripState(
                    stage: sleepVM.status?.stage ?? 0,
                    isRunning: sleepVM.isRunning,
                    cancelled: sleepVM.status?.cancelled == true,
                    error: !(sleepVM.status?.error ?? "").isEmpty,
                    read: bubbleCtx.read,
                    total: bubbleCtx.total
                ),
                showsCaughtUpWorm: stageStripShowsCaughtUpWorm(mood: mood, debt: debt)
            )

            moodDetailLine(mood: mood, debt: debt)

            if let engine = sleepVM.status?.lastEngine {
                engineLine(engine, detail: sleepVM.status?.engineDetail)
            }

            // Review fix L1/L4: `cancelled`/`episodeCap`/`episodesQueued` were
            // decoded but read by no view — only the free-text `progress`
            // sentence mentioned either. Both get a real, structured
            // readout here rather than depending on the human sitting there
            // to parse a sentence.
            if sleepVM.status?.cancelled == true {
                cancelledBanner
            }
            if let s = sleepVM.status, s.episodesQueued > s.episodesTotal {
                capBanner(processed: s.episodesTotal, queued: s.episodesQueued, cap: s.episodeCap)
            }

            // Non-fatal warnings (e.g. LEANN episode index rebuild failed
            // even though entity writes + commit succeeded). Surfaced so a
            // "completed with warnings" cycle never looks like a clean pass.
            if let warning = sleepVM.status?.indexWarning, !warning.isEmpty {
                warningBanner(warning)
            }
        }
        .padding(CicadaTheme.spacingLG)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard()
    }

    /// The one thing the hero's meter CANNOT say: that there is no baseline
    /// at all.
    ///
    /// G125 v3 Task 5 (R-A8) deleted this function's running branch — the
    /// `Text("Stage \(stage) of 5")` and the bare `ProgressView` the stage
    /// strip replaced. The round-2 live check deleted its idle branch for the
    /// same reason one step further on: it drew `Rested n% — volume v%, age
    /// a%` directly under a hero meter already labelled `Rested n%`, so **the
    /// same number was on screen twice** (R-A5 — one number, one place). The
    /// volume/age split did not vanish with it: it is the meter label's hover
    /// text now (`heroMeterHelp`), which is where a breakdown belongs.
    ///
    /// What is left is the branch the meter has no way to draw. `heroMeter`
    /// returns `nil` when `restedPct` is nil, so without this line a bank
    /// where Sleep has never run would show nothing at all where the meter
    /// sits — and silence reads as "fine", which is the opposite of the truth.
    ///
    /// The `.sleeping` guard survives as an explicit empty branch: a baseline
    /// is what the queue looks like BETWEEN cycles, so mid-cycle it would sit
    /// stale next to a live readout.
    @ViewBuilder
    private func moodDetailLine(mood: BookwormState, debt: SleepDebtView?) -> some View {
        if case .sleeping = mood {
            EmptyView()
        } else if let debt, debt.restedPct == nil {
            // No baseline: the queue is empty and Sleep has never run in
            // this bank — an honest state, not a fabricated 100%.
            Text("No baseline yet — Sleep hasn't run in this bank.")
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
        }
    }

    /// "Episode cap reached" — informational, not a warning: the cap is a
    /// deliberate safety feature (spec: bound one cycle's wall-clock instead
    /// of an unbounded first run), and the remaining episodes are simply
    /// picked up next cycle, nothing lost.
    private func capBanner(processed: Int, queued: Int, cap: Int) -> some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingSM) {
            Image(systemName: "tray.and.arrow.down")
                .font(CicadaTheme.font(size: 12))
                .foregroundStyle(CicadaTheme.accent)
            VStack(alignment: .leading, spacing: 2) {
                Text("Episode cap reached (\(cap))")
                    .font(CicadaTheme.font(size: 11, weight: .semibold))
                    .foregroundStyle(CicadaTheme.textPrimary)
                Text("\(processed) of \(queued) processed — the rest stay queued for the next cycle.")
                    .font(CicadaTheme.font(size: 10))
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            Spacer()
        }
        .padding(CicadaTheme.spacingSM)
        .frame(maxWidth: .infinity)
        .background(CicadaTheme.accent.opacity(0.10))
        .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
    }

    /// The last cycle stopped early because of a `/sleep/cancel` request
    /// (as opposed to completing normally, or a cancel that arrived too
    /// late to matter — see `sleep_cycle._cycle_cancelled`). Informational
    /// tone, matching `Copy.cancelSleepExplainer`'s own promise: nothing
    /// was lost.
    private var cancelledBanner: some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingSM) {
            Image(systemName: "xmark.circle")
                .font(CicadaTheme.font(size: 12))
                .foregroundStyle(CicadaTheme.accent)
            VStack(alignment: .leading, spacing: 2) {
                Text("Cancelled")
                    .font(CicadaTheme.font(size: 11, weight: .semibold))
                    .foregroundStyle(CicadaTheme.textPrimary)
                Text("Stopped cleanly before any writes — nothing was lost.")
                    .font(CicadaTheme.font(size: 10))
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            Spacer()
        }
        .padding(CicadaTheme.spacingSM)
        .frame(maxWidth: .infinity)
        .background(CicadaTheme.accent.opacity(0.10))
        .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
    }

    // MARK: Warning banner

    private func warningBanner(_ text: String) -> some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingSM) {
            Image(systemName: "exclamationmark.triangle")
                .font(CicadaTheme.font(size: 12))
                .foregroundStyle(CicadaTheme.warning)
            VStack(alignment: .leading, spacing: 2) {
                Text("Completed with warnings")
                    .font(CicadaTheme.font(size: 11, weight: .semibold))
                    .foregroundStyle(CicadaTheme.textPrimary)
                Text(text)
                    .font(CicadaTheme.font(size: 10))
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            Spacer()
        }
        .padding(CicadaTheme.spacingSM)
        .frame(maxWidth: .infinity)
        .background(CicadaTheme.warning.opacity(0.10))
        .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
    }

    // MARK: Engine line

    /// Which engine the last cycle ran on. Named, not implied — a Sleep page
    /// that says "check API credits" while running on a subscription is the
    /// exact confusion this replaces.
    private func engineLine(_ engine: String, detail: String?) -> some View {
        HStack(spacing: CicadaTheme.spacingXS) {
            Text("ENGINE")
                .font(CicadaTheme.font(size: 9, weight: .semibold, design: .monospaced))
                .foregroundStyle(CicadaTheme.textTertiary)
                .tracking(1.1)
            Text(Copy.engineLabel(engine))
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textSecondary)
            if let detail, !detail.isEmpty {
                Text("· \(detail)")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .lineLimit(2)
            }
            Spacer()
        }
    }

    // MARK: Error banner

    private func errorBanner(_ text: String) -> some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingSM) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(CicadaTheme.font(size: 13))
                .foregroundStyle(CicadaTheme.danger)
            VStack(alignment: .leading, spacing: 2) {
                Text("Sleep cycle error")
                    .font(CicadaTheme.font(size: 12, weight: .semibold))
                    .foregroundStyle(CicadaTheme.textPrimary)
                Text(text)
                    .font(CicadaTheme.font(size: 11))
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            Spacer()
        }
        .padding(CicadaTheme.spacingMD)
        .frame(maxWidth: .infinity)
        .background(CicadaTheme.danger.opacity(0.12))
        .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
    }
}
