import SwiftUI

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

            ScrollView {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                    headerRow
                    deskCard
                    if let error = sleepVM.lastError ?? sleepVM.errorMessage, !error.isEmpty {
                        errorBanner(error)
                    }
                    StudyListCard(rows: studyListRows, episodes: sleepVM.queuedEpisodes, onSelectEntity: onSelectEntity)
                    ConsolidationHistoryCard(
                        entries: sleepVM.history,
                        details: sleepVM.details,
                        expanded: sleepVM.expanded,
                        onToggle: toggleHistory,
                        onSelectEntity: onSelectEntity
                    )
                }
                .padding(CicadaTheme.spacingXL)
                .frame(maxWidth: 760)
                .frame(maxWidth: .infinity, alignment: .top)
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

    /// The mascot card, now "the desk": the speech bubble (G125 Task 5) over
    /// the 24×24 colour bookworm (G107) at 120 pt — five whole cells per
    /// point-row, so the pixels stay crisp (ruling R3) — with the bracketed,
    /// monospaced status line kept as its caption, beside the book pile
    /// (Task 6) that encodes queued volume on a log scale. Both the mood and
    /// the per-origin counts prefer the continuously-updating SSE `sleep`
    /// event (`store.sleepEvent`) and fall back to the last REST
    /// `/sleep/status` fetch, via `resolveSleepDebt`/`resolveProgressPct`/
    /// `resolveOriginCounts`.
    private var deskCard: some View {
        let debt = resolveSleepDebt(sse: store.sleepEvent, status: sleepVM.status)
        let progress = resolveProgressPct(sse: store.sleepEvent, status: sleepVM.status)
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

        return VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            HStack(alignment: .bottom, spacing: CicadaTheme.spacingXL) {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                    SpeechBubbleView(text: sleepBubbleText(mood, bubbleCtx))
                    BookwormView(
                        state: mood,
                        pointSize: 120,
                        caption: sleepDebtBracketText(mood, debt: debt),
                        captionFont: .system(size: 20, weight: .semibold, design: .monospaced),
                        captionColor: sleepDebtBracketColor(mood),
                        alignment: .leading
                    )
                }
                Spacer(minLength: 0)
                BookPileView(books: books)
                    .frame(width: 170, height: 150, alignment: .bottomLeading)
            }

            moodDetailLine(mood: mood, debt: debt, progress: progress)

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

    /// Under the bubble/worm/pile row: while a cycle is running, which of
    /// the five stages it's on plus the same overall progress bar that used
    /// to live in the retired `progressCard` (Stage 1's own live percent
    /// stays visible too — it's the only stage with a natural per-episode
    /// unit; see `sleep_cycle.progress_pct`'s docstring). While idle, the
    /// Rested % breakdown — "explainable, not a black box" (spec).
    @ViewBuilder
    private func moodDetailLine(mood: BookwormState, debt: SleepDebtView?, progress: Int?) -> some View {
        if case .sleeping(let stage) = mood {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                Text("Stage \(stage) of 5")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                ProgressView(value: sleepVM.progressFraction)
                    .progressViewStyle(.linear)
                    .tint(CicadaTheme.accent)
                    .frame(maxWidth: 240)
                    .animation(.easeInOut(duration: 0.35), value: sleepVM.progressFraction)
                if let progress {
                    Text("Stage 1: \(progress)%")
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
            }
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
                .font(.system(size: 12))
                .foregroundStyle(CicadaTheme.accent)
            VStack(alignment: .leading, spacing: 2) {
                Text("Episode cap reached (\(cap))")
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(CicadaTheme.textPrimary)
                Text("\(processed) of \(queued) processed — the rest stay queued for the next cycle.")
                    .font(.system(size: 10))
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
                .font(.system(size: 12))
                .foregroundStyle(CicadaTheme.accent)
            VStack(alignment: .leading, spacing: 2) {
                Text("Cancelled")
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(CicadaTheme.textPrimary)
                Text("Stopped cleanly before any writes — nothing was lost.")
                    .font(.system(size: 10))
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
                .font(.system(size: 12))
                .foregroundStyle(CicadaTheme.warning)
            VStack(alignment: .leading, spacing: 2) {
                Text("Completed with warnings")
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(CicadaTheme.textPrimary)
                Text(text)
                    .font(.system(size: 10))
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
                .font(.system(size: 9, weight: .semibold, design: .monospaced))
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
                .font(.system(size: 13))
                .foregroundStyle(CicadaTheme.danger)
            VStack(alignment: .leading, spacing: 2) {
                Text("Sleep cycle error")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(CicadaTheme.textPrimary)
                Text(text)
                    .font(.system(size: 11))
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
