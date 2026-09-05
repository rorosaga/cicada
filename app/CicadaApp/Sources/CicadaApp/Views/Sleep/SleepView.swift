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

// MARK: - Sleep Dashboard — the study desk (G125)

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

    /// The page's subject: the room, what the cycle is doing, and what is
    /// waiting for it. The error banner keeps its place between the two — it is
    /// news about the cycle the desk card is describing.
    @ViewBuilder
    private var leftColumn: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            deskCard
            if let error = sleepVM.lastError ?? sleepVM.errorMessage, !error.isEmpty {
                errorBanner(error)
            }
            StudyListCard(rows: studyListRows, episodes: sleepVM.queuedEpisodes, onSelectEntity: onSelectEntity)
        }
    }

    /// The page's margin: where memory came from, and what past cycles did with
    /// it. Both are projections of domains the caller already holds — neither
    /// card fetches anything (R-A10).
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
        withAnimation(.easeInOut(duration: 0.15)) {
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
            Text("Sleep Cycle")
                .font(CicadaTheme.titleFont)
                .foregroundStyle(CicadaTheme.textPrimary)
            Text(Copy.sleepSubtitle)
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textSecondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
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

    /// The IDLE explainer, and only that: the Rested % breakdown —
    /// "explainable, not a black box" (spec).
    ///
    /// G125 v3 Task 5 (R-A8) deleted this function's running branch. It used
    /// to draw `Text("Stage \(stage) of 5")`, a bare linear `ProgressView`
    /// over `sleepVM.progressFraction` and `Text("Stage 1: \(progress)%")` —
    /// a bar that moved in five jumps, a percentage with no noun, and a stage
    /// number with no idea what that stage does. `SleepStageStrip` says all
    /// three things at once and says which stage is which, so the running
    /// readout is now the strip plus the hero's `Read n of m` meter.
    ///
    /// The `.sleeping` guard survives as an explicit empty branch rather than
    /// falling through to the Rested line: Rested % is what the queue looks
    /// like BETWEEN cycles, and showing it mid-cycle would put a stale
    /// baseline next to a live one.
    @ViewBuilder
    private func moodDetailLine(mood: BookwormState, debt: SleepDebtView?) -> some View {
        if case .sleeping = mood {
            EmptyView()
        } else if let debt {
            if let rested = debt.restedPct {
                Text("Rested \(rested)% — volume \(debt.volumePct)%, age \(debt.agePct)%")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            } else {
                // No baseline: the queue is empty and Sleep has never run in
                // this bank — an honest state, not a fabricated 100%.
                Text("No baseline yet — Sleep hasn't run in this bank.")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
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
