import SwiftUI

// MARK: - The page's arrangement (Track Z Z3)

/// The Sleep page's one column (Track Z R-Z6 / §4.1 — R-A1's two columns are
/// retired). 760 pt is the width the stacked page always had; it is not
/// scaled because the room is the widest thing in it and fits at every zoom
/// step (`SleepLayoutTests`, Z-P23).
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
    /// Track Z Z10 — Increase Contrast hides the optional sky band (§11).
    @Environment(\.colorSchemeContrast) private var contrast
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
    /// Spec decision 16 — Details is closed by default and remembered per
    /// viewer. `@AppStorage` is a per-viewer convenience, which is exactly
    /// the use browser-style storage is for: losing it only closes Details.
    @AppStorage(SleepDetails.openKey) private var detailsOpen = SleepDetails.defaultOpen
    /// The Details section a tail link asked for, held until Details has been
    /// built and its anchor exists (`openDetails`).
    @State private var pendingScroll: DetailsSection?
    /// Track Z Z5 — the room's interaction state (gaze, perk, the answer
    /// ladder). Page-local `@State`: a tab switch tears it down, so an answer
    /// never outlives the visit it was asked in.
    @State private var room = RoomModel()

    var body: some View {
        let page = resolvePage()
        ZStack {
            // No .ignoresSafeArea(): the title bar is darkened at the window level
            // (CicadaApp). Ignoring the safe area here pushed content under the menu
            // bar and stretched the window to full screen height.
            CicadaTheme.background

            // Track Z Z10 (spec decision 16) — the optional sky band: behind
            // everything, fixed across the top, following the window's weather.
            // `SkyBand.ships` is the one switch (Z-B16).
            if SkyBand.isDrawn(contrast: contrast) {
                VStack(spacing: 0) {
                    SleepSkyBand(weather: windowWeather(for: page.mood))
                    Spacer(minLength: 0)
                }
            }

            // One column at every width (R-Z6): the room card, the one
            // Details row, and Details itself only while it is open.
            ScrollViewReader { proxy in
                ScrollView {
                    VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                        headerRow
                        // R-A12: `.saturation` is UNCONDITIONAL, at the
                        // identity 1.0 while live — an `if` around it would
                        // change the card's structural identity and rebuild
                        // it every time the connection flaps.
                        roomCard(page)
                            .saturation(liveness.saturation)
                        DetailsDisclosureRow(open: detailsOpen) {
                            withAnimation(SleepMotion.disclosure(reduceMotion: reduceMotion)) { detailsOpen.toggle() }
                        }
                        if detailsOpen {
                            SleepDetails(page: page, liveness: liveness, pageError: pageError,
                                         status: sleepVM.status, episodes: sleepVM.queuedEpisodes,
                                         history: sleepVM.history, details: sleepVM.details,
                                         expanded: sleepVM.expanded, onToggleHistory: toggleHistory,
                                         onSelectEntity: onSelectEntity, room: room)
                        }
                    }
                    .padding(CicadaTheme.spacingXL)
                    .frame(maxWidth: SleepLayout.contentWidth)
                    .frame(maxWidth: .infinity, alignment: .top)
                    // I4 — a mood change resets the ladder: an answer about
                    // the state that just ended is no longer true, and any
                    // feed line about a moment that has passed (Z-B11).
                    .onChange(of: page.mood.caseName) { _, _ in room.dismissSlot() }
                }
                // Details is built only while open, so an anchor inside it
                // exists one update after `detailsOpen` flips: scroll then.
                .onChange(of: pendingScroll) { _, section in
                    guard let section else { return }
                    DispatchQueue.main.async {
                        withAnimation(SleepMotion.disclosure(reduceMotion: reduceMotion)) {
                            proxy.scrollTo(section.anchorID, anchor: .top)
                        }
                        pendingScroll = nil
                    }
                }
            }
        }
        .task {
            if !loadedOnce {
                loadedOnce = true
                await sleepVM.load()
            }
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
                                            error: sleepVM.status?.error)
                if room.cycleEnded(real: real, edgeBaseline: lastCycleEntry(sleepVM.history)?.commitHash,
                                   history: sleepVM.history) != nil {
                    celebrateCompletion()
                }
            }
        }
        .onChange(of: sleepVM.history) { _, history in
            if room.resolveCompletion(history: history) != nil { celebrateCompletion() }
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

    /// Track Z Z1 — the page, resolved once per body (§9). Every reader below
    /// takes its numbers from this value, so the room, the queue and the
    /// controls cannot disagree about which reading they show (H1, now
    /// structural). `now` is the body's own clock read — `studyRows` ages and
    /// the 6 s digest window already depended on it.
    private func resolvePage(now: Date = .now) -> SleepPageModel {
        SleepPageModel.resolve(
            status: sleepVM.status, sse: store.sleepEvent, queued: sleepVM.queuedEpisodes,
            schedule: sleepVM.schedule, enginePreview: sleepVM.enginePreview, history: sleepVM.history,
            storeStatus: store.status.value,
            queueLoad: StudyListCard.loadState(status: store.status.value,
                                               isLoading: store.status.isEmpty && store.status.isRefreshing,
                                               error: store.domainErrors[.status]),
            justFinishedAt: justFinishedAt, intakeInFlight: store.intakeInFlight, now: now)
    }

    /// The one error the page has to tell, if there is one — `lastError`
    /// preferred over the transient `errorMessage`, which is how the page has
    /// always resolved it.
    ///
    /// This drives Details › Last cycle and nothing else. It is deliberately NOT what
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
    /// keeps its one job — driving Details › Last cycle's error banner, which
    /// `SleepDetails` places outside every desaturated group.
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

    // MARK: Details (Track Z Z3, R-Z6)

    /// Open Details and land on one section — a tail link's destination
    /// (Z-P5). The scroll waits for `pendingScroll`'s `onChange`, because a
    /// closed Details has no anchors to scroll to yet.
    private func openDetails(_ section: DetailsSection) {
        withAnimation(SleepMotion.disclosure(reduceMotion: reduceMotion)) { detailsOpen = true }
        pendingScroll = section
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

    /// T7 / I17 — open Details, expand the cycle's history row (its detail
    /// loads through the one cached path, `toggleHistory` → `loadDetail`),
    /// and land on Past nights. The link clears as it is followed: what
    /// changed is now on screen, so the sentence goes back to the state.
    private func showWhatChanged() {
        guard let commit = room.followWhatChanged() else { return }
        if sleepVM.expanded != commit { toggleHistory(commit) }
        openDetails(.pastNights)
    }

    // MARK: Header

    private var headerRow: some View {
        // The title is `PageTitle`, the same view `PageHeader` draws (Z-B4):
        // the page keeps its own row because the title sits inside the centred
        // column (R-Z6) with the staleness chip beside it (R-A12).
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
                // The subtitle stopped rendering (Track Z §4.1); it survives as
                // the title's VoiceOver hint — on this one element, not the
                // page's `ZStack`, where it would spread to every button.
                PageTitle(Copy.sleepPageTitle)
                    .accessibilityHint(Copy.sleepSubtitle)
                // R-A12: the chip explains the dimming below it, so it stays at
                // full contrast and sits outside every desaturated group.
                if let asOf = liveness.asOf {
                    stalenessChip(asOf)
                }
                Spacer(minLength: 0)
            }
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
        // (`SleepHero`, `BookPile` and `SleepStageStrip` all do this). Without it SwiftUI propagates the
        // container's label to each child and VoiceOver reads the whole
        // sentence twice, once for the glyph and once for the text.
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(Copy.notConnectedExplainer) \(Copy.asOf(asOf))")
    }

    // MARK: The desk (G106 amendment; G107 art; G125 the study desk)

    /// The mascot card, now "the study room" (G125 v3 Task 3): a night
    /// window, a floor lamp, a plant, a cushion and a mug,
    /// with the 24×24 colour bookworm (G107) sitting on the cushion at 120 pt
    /// — five whole cells per point-row, so the pixels stay crisp (ruling R3)
    /// — and the REAL `BookPileView` standing in the column
    /// `deskSceneLayout` reserves for it beside him. Nothing in the room is
    /// painted books (P10): the page's one volume encoding is that pile.
    ///
    /// Every value it draws comes from `page` (Track Z Z1), which resolved the
    /// SSE-over-REST precedence (`store.sleepEvent` first, the last
    /// `/sleep/status` fetch second) once for the whole body — the card no
    /// longer re-derives the mood, the pile or the strip on its own.
    ///
    /// The scene box is a FIXED height at a given zoom (R-A2), so idle →
    /// running → idle never reflows the art: the mood changes the worm's
    /// frames, never the room's geometry.
    ///
    /// Track Z Z2 (R-Z5): the bubble that floated above the room is gone. The
    /// worm speaks in one fixed slot directly under it — the display-face sentence —
    /// then the one control and the whisper line, all centred on the room.
    ///
    /// Track Z Z3 (R-Z6): this card IS the default view. The readout, the
    /// banners and the engine line moved into Details; the strip stays, but
    /// only with news, and at the card's last row (Z-P9) so neither the
    /// sentence nor the control the person just pressed moves when it appears.
    private func roomCard(_ page: SleepPageModel) -> some View {
        // One reading feeds the status line AND the answers (Task 6), so the
        // worm can never answer from a different snapshot than it states.
        let context = page.roomContext(recentCycleCommit: room.recentCycleCommit)
        let status = roomSentence(context)
        let answers = wormAnswers(context)

        return VStack(alignment: .center, spacing: CicadaTheme.spacingMD) {
            // Track Z Z5 (R-Z8): the room is its own view — the inert art,
            // the worm on its lattice, the real pile, and a hotspot layer
            // derived from the same pure layout. The bracket line (P8) moved
            // from this group's label onto the worm's own element as its value.
            StudyRoom(page: page, statusLine: status, answers: answers, room: room,
                      episodes: sleepVM.queuedEpisodes, onOpenDetails: openDetails,
                      onWhatChanged: room.recentCycleCommit == nil ? nil : { showWhatChanged() },
                      reachable: liveness == .live)
                .accessibilitySortPriority(RoomA11yOrder.room)

            // R-Z5 — the one slot the worm speaks in; an answer replaces the
            // status here (R-Z7). Every action has its destination since
            // Task 8 (Z-P5's seam is gone), so the switch is exhaustive: a
            // new action cannot ship without somewhere to go.
            RoomSentenceView(line: status, answers: answers, room: room,
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
                             })
            SleepControlRow(consolidateEnabled: page.consolidateEnabled,
                            queuedCount: page.queuedCount, manualEngine: page.manualEngine)
                .accessibilitySortPriority(RoomA11yOrder.control)
            whisperRow(page)
                .accessibilitySortPriority(RoomA11yOrder.whisper)

            // R-A8 / R-Z6 — the five-stage strip, only while a cycle runs or
            // after one was cancelled or failed (its frozen record, P15).
            if stageStripIsVisible(isRunning: page.isRunning, cancelled: page.cancelled,
                                   failed: page.cycleError != nil) {
                SleepStageStrip(pips: page.pips)
            }
        }
        .accessibilityElement(children: .contain)
        .padding(CicadaTheme.spacingLG)
        .frame(maxWidth: .infinity)
        .glassCard()
    }

    /// The schedule in one quiet line (§7.2) — the lamp's text twin (R-A3),
    /// replacing the queue card's schedule row and footer (Z-P4). Since Z6 it
    /// is a control: it opens the same `LampPopover` the lamp does, anchored
    /// here (Z-P25). Its "Change…" link and the "Scheduled runs use …" note
    /// left with that step — the popover carries both, and its engine line
    /// shows the scheduled engine ALWAYS, not only when it differs, so ruling
    /// 4 is on screen at the moment someone chooses to schedule.
    private func whisperRow(_ page: SleepPageModel) -> some View {
        Button { room.lampPopover = .whisper } label: {
            HStack(spacing: CicadaTheme.spacingSM) {
                Image(systemName: "moon.zzz")
                    .font(CicadaTheme.font(size: 11))
                    .iconHover()
                Text(whisperLine(scheduleText: page.scheduleText, nextRunText: page.nextRunText,
                                 lampLit: page.lampLit))
                    .font(CicadaTheme.captionFont)
            }
            .foregroundStyle(CicadaTheme.textTertiary)
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .roomLinkCursor()
        // R-A14 — "Next run —" is a value with a reason; an empty help
        // string renders no tooltip, so a real time carries none.
        .help(page.nextRunText.hasSuffix("—") ? Copy.nextRunUnknownReason : "")
        .accessibilityHint(Copy.lampHint)
        .popover(isPresented: Binding(get: { room.lampPopover == .whisper },
                                      set: { if !$0 { room.lampPopover = nil } }),
                 arrowEdge: .bottom) { LampPopover(page: page) }
        .frame(maxWidth: .infinity)
    }
}

/// The one row that opens Details (R-Z6), with Meadow's hover (Z-B15): the
/// chevron acknowledges the pointer once (`iconHover`) and the words brighten
/// — a fill change, never a lift, because a row is not a card (R-M14). Its
/// own `@State`, so a hover never re-evaluates the page. `if detailsOpen {}`
/// in the page's `body`, not an opacity, is what keeps a closed Details free.
private struct DetailsDisclosureRow: View {
    let open: Bool
    let toggle: () -> Void

    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        Button(action: toggle) {
            HStack(spacing: CicadaTheme.spacingSM) {
                Image(systemName: open ? "chevron.down" : "chevron.right")
                    .font(CicadaTheme.font(size: 10, weight: .semibold))
                    .frame(width: 12)
                    .iconHover(hovering: hovering)
                Text(Copy.sleepDetails)
                    .font(CicadaTheme.font(size: 13, weight: .semibold))
                Spacer(minLength: 0)
            }
            .foregroundStyle(hovering ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
            .animation(SleepMotion.hover(reduceMotion: reduceMotion), value: hovering)
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .onHover { hovering = $0 }
        .accessibilityLabel(Copy.sleepDetails)
        .accessibilityValue(open ? "expanded" : "collapsed")
    }
}
