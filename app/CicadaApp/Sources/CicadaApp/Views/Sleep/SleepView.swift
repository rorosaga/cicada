import SwiftUI

// MARK: - Sleep Dashboard

struct SleepView: View {
    @Binding var selectedTab: AppTab
    @Environment(SleepViewModel.self) private var sleepVM
    // H1: the "EPISODES QUEUED" header and `SleepQueueCard` above it must
    // agree on one count. `Store.status` is the SSE-live source; reading it
    // here (instead of only `sleepVM.queuedEpisodes.count`, which is fetched
    // once per visit) keeps the two readouts from disagreeing when an MCP
    // capture lands while this page is open.
    @Environment(Store.self) private var store
    @State private var scheduleDate: Date = Self.defaultDate()
    @State private var scheduleEnabled: Bool = false
    @State private var loadedOnce: Bool = false
    @State private var showUploadOverlay = false
    // Default to descending (newest first) — the common case when reviewing
    // what's about to be consolidated.
    @State private var sortAscending: Bool = false
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

    private var sortedQueuedEpisodes: [EpisodeQueueItem] {
        let base = sleepVM.queuedEpisodes
        return sortAscending ? base : base.reversed()
    }

    private var sortedProcessedEpisodes: [EpisodeQueueItem] {
        let base = sleepVM.processedEpisodes
        return sortAscending ? base : base.reversed()
    }

    private static func defaultDate() -> Date {
        var comps = DateComponents()
        comps.hour = 3
        comps.minute = 0
        return Calendar.current.date(from: comps) ?? Date()
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
                    moodCard
                    if let engine = sleepVM.status?.lastEngine {
                        engineLine(engine, detail: sleepVM.status?.engineDetail)
                    }
                    if let error = sleepVM.lastError ?? sleepVM.errorMessage, !error.isEmpty {
                        errorBanner(error)
                    }
                    SleepQueueCard()
                    pauseCard
                    SleepDebtBreakdown(episodes: sleepVM.queuedEpisodes)
                    progressCard
                    queueCard
                }
                .padding(CicadaTheme.spacingXL)
                .frame(maxWidth: 760)
                .frame(maxWidth: .infinity, alignment: .top)
            }

            // Top-right: Sleep + Upload + Help buttons — same pattern as
            // GraphContainerView and TopicsView so the Import (Upload)
            // button is available from every primary screen.
            VStack {
                HStack {
                    Spacer()
                    TopBarControls(
                        selectedTab: $selectedTab,
                        showUploadOverlay: $showUploadOverlay
                    )
                    .padding(CicadaTheme.spacingLG)
                }
                Spacer()
            }

            if showUploadOverlay {
                UploadOverlay(isPresented: $showUploadOverlay)
                    .transition(.opacity)
            }
        }
        .animation(.spring(duration: 0.3), value: showUploadOverlay)
        .task {
            if !loadedOnce {
                loadedOnce = true
                await sleepVM.load()
                syncScheduleState()
            }
        }
        .onChange(of: sleepVM.schedule) { _, _ in
            syncScheduleState()
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
        .onChange(of: showUploadOverlay) { _, isOpen in
            // When the import overlay closes, refresh the episode queue so
            // newly-uploaded conversations show up immediately.
            if !isOpen {
                Task { @MainActor in await sleepVM.load() }
            }
        }
        // PR #19 review: the header count reads SSE-live `store.status`
        // while the rows below it stay pinned to whatever `sleepVM.load()`
        // last fetched, once per visit. A capture (or another Sleep cycle
        // finishing elsewhere) bumps the live count without touching the
        // rows, so the header and the list contradict each other for as
        // long as the page stays open. One freshness model: whenever the
        // live unprocessed count disagrees with the loaded rows, refetch.
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

    private func syncScheduleState() {
        scheduleEnabled = sleepVM.schedule.enabled
        var comps = DateComponents()
        comps.hour = sleepVM.schedule.hour
        comps.minute = sleepVM.schedule.minute
        if let d = Calendar.current.date(from: comps) {
            scheduleDate = d
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

    // MARK: Mood (G106 amendment; G107 art)

    /// The mascot card: the 24×24 colour bookworm (G107) at 120 pt — five
    /// whole cells per point-row, so the pixels stay crisp (ruling R3) — in
    /// the mood `deriveSleepPageMood` derives, with the bracketed,
    /// monospaced status line kept underneath as its caption (ruling R9:
    /// same text, same colour, now under the worm rather than standing in
    /// for it), plus the Rested % reading and the components it's built
    /// from — "explainable, not a black box" (spec). Both the mood and the
    /// debt numbers prefer the continuously-updating SSE `sleep` event
    /// (`store.sleepEvent`) and fall back to the last REST `/sleep/status`
    /// fetch, via `resolveSleepDebt`/`resolveProgressPct`.
    private var moodCard: some View {
        let debt = resolveSleepDebt(sse: store.sleepEvent, status: sleepVM.status)
        let progress = resolveProgressPct(sse: store.sleepEvent, status: sleepVM.status)
        let mood = deriveSleepPageMood(status: sleepVM.status, debt: debt, justFinishedAt: justFinishedAt)
        return VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            BookwormView(
                state: mood,
                pointSize: 120,
                caption: sleepDebtBracketText(mood, debt: debt),
                captionFont: .system(size: 24, weight: .semibold, design: .monospaced),
                captionColor: sleepDebtBracketColor(mood),
                alignment: .leading
            )

            moodDetailLine(mood: mood, debt: debt, progress: progress)
        }
        .padding(CicadaTheme.spacingLG)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard()
    }

    @ViewBuilder
    private func moodDetailLine(mood: BookwormState, debt: SleepDebtView?, progress: Int?) -> some View {
        if case .sleeping = mood, let progress {
            // Progress % — literally "episodes processed / episodes in this
            // cycle", live during Stage 1 (the only stage with a natural
            // per-episode unit; see the backend's `sleep_cycle.progress_pct`
            // docstring). Absent (this branch skipped) once Stage 1 finishes
            // rather than freezing at 100% while stages 2-5 still run.
            Text("Stage 1 progress: \(progress)%")
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
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

    // MARK: Schedule (quick control — the full editor moved to Settings → Schedule)

    /// One of the Sleep page's three quick controls (run — `SleepQueueCard`
    /// — pause, cancel — G106 amendment). Flips the SAME `ScheduleConfig.
    /// enabled` the Settings → Schedule tab's time picker edits; the hour/
    /// minute this toggle preserves is whatever was last set there, never
    /// reset to a default. No time picker here on purpose — that lives in
    /// exactly one place (`SettingsSleepView`) so the two can't disagree.
    private var pauseCard: some View {
        HStack(spacing: CicadaTheme.spacingMD) {
            Image(systemName: scheduleEnabled ? "moon.fill" : "moon.zzz")
                .font(.system(size: 13, weight: .medium))
                .foregroundStyle(scheduleEnabled ? CicadaTheme.accent : CicadaTheme.textTertiary)
                .frame(width: 28, height: 28)
                .background(Circle().fill((scheduleEnabled ? CicadaTheme.accent : CicadaTheme.textTertiary).opacity(0.12)))
                .overlay(Circle().stroke(CicadaTheme.border, lineWidth: 1))

            VStack(alignment: .leading, spacing: 2) {
                Text(scheduleEnabled ? "Auto-run at \(formattedTime(scheduleDate)) daily" : "Manual triggers only")
                    .font(CicadaTheme.headingFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                Text("Change the time in \(Copy.settingsSchedule).")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }

            Spacer()

            Button {
                scheduleEnabled.toggle()
                commitSchedule()
            } label: {
                Text(scheduleEnabled ? Copy.pauseAutoRun : Copy.resumeAutoRun)
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .padding(.horizontal, CicadaTheme.spacingLG)
                    .padding(.vertical, CicadaTheme.spacingSM)
                    .background(CicadaTheme.surfaceElevated)
                    .clipShape(Capsule())
            }
            .buttonStyle(.cicadaPlain)
            .accessibilityLabel(scheduleEnabled ? Copy.pauseAutoRun : Copy.resumeAutoRun)
        }
        .padding(CicadaTheme.spacingLG)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard()
    }

    private func commitSchedule() {
        let comps = Calendar.current.dateComponents([.hour, .minute], from: scheduleDate)
        let new = ScheduleConfig(
            enabled: scheduleEnabled,
            hour: comps.hour ?? 3,
            minute: comps.minute ?? 0
        )
        Task { @MainActor in
            await sleepVM.updateSchedule(new)
        }
    }

    private func formattedTime(_ date: Date) -> String {
        let f = DateFormatter()
        f.timeStyle = .short
        f.dateStyle = .none
        return f.string(from: date)
    }

    // MARK: Progress

    private var progressCard: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            // H1: the trigger lives solely on `SleepQueueCard` now (spec
            // §2.8/§2.9 — "one voice"). This card is read-only progress.
            Text("PROGRESS")
                .font(.system(size: 10, weight: .semibold, design: .monospaced))
                .foregroundStyle(CicadaTheme.textTertiary)
                .tracking(1.2)

            ProgressView(value: sleepVM.progressFraction)
                .progressViewStyle(.linear)
                .tint(CicadaTheme.accent)
                .animation(.easeInOut(duration: 0.35), value: sleepVM.progressFraction)

            Text(sleepVM.status?.progress ?? "Idle")
                .font(.system(size: 12))
                .foregroundStyle(CicadaTheme.textSecondary)
                .frame(maxWidth: .infinity, alignment: .leading)

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

            HStack(spacing: CicadaTheme.spacingMD) {
                counterChip(
                    label: "Episodes",
                    value: sleepVM.status?.episodesTotal ?? 0,
                    caption: episodesCaption
                )
                counterChip(
                    label: "Entities",
                    value: (sleepVM.status?.entitiesCreated ?? 0)
                        + (sleepVM.status?.entitiesUpdated ?? 0)
                )
                counterChip(
                    label: "Relationships",
                    value: sleepVM.status?.relationshipsCreated ?? 0
                )
                counterChip(label: "Skills", value: sleepVM.status?.skillsDetected ?? 0)
            }
        }
        .padding(CicadaTheme.spacingLG)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard()
    }

    /// "25 of 230" under the Episodes chip when the cap truncated this
    /// cycle — `nil` (chip shows just the count, as before) otherwise.
    private var episodesCaption: String? {
        guard let s = sleepVM.status, s.episodesQueued > s.episodesTotal else { return nil }
        return "of \(s.episodesQueued) queued"
    }

    /// Episode cap (sleep control) truncated this cycle — informational,
    /// not a warning: the cap is a deliberate safety feature (spec: bound
    /// one cycle's wall-clock instead of an unbounded first run), and the
    /// remaining episodes are simply picked up next cycle, nothing lost.
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

    private func counterChip(label: String, value: Int, caption: String? = nil) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label.uppercased())
                .font(.system(size: 9, weight: .semibold, design: .monospaced))
                .foregroundStyle(CicadaTheme.textTertiary)
                .tracking(1.0)
            Text("\(value)")
                .font(.system(size: 20, weight: .semibold, design: .rounded))
                .foregroundStyle(CicadaTheme.textPrimary)
                .contentTransition(.numericText())
                .animation(.easeInOut(duration: 0.3), value: value)
            if let caption {
                Text(caption)
                    .font(.system(size: 9))
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
        }
        .padding(.horizontal, CicadaTheme.spacingMD)
        .padding(.vertical, CicadaTheme.spacingSM)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(CicadaTheme.surfaceHover)
        .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
    }

    // MARK: Queue

    /// The count `queueCard`'s header and `SleepQueueCard` must agree on
    /// (H1): SSE-live `store.status.episodes.unprocessed` when a snapshot has
    /// arrived, falling back to the once-per-visit `sleepVM.queuedEpisodes`
    /// count before the first one does. Pulled out as a pure function so the
    /// precedence is unit-testable without standing up a view.
    static func queueCount(status: StatusSnapshot?, fallback: Int) -> Int {
        status?.episodes.unprocessed ?? fallback
    }

    /// Whether the SSE-live unprocessed count has drifted from the rows
    /// `sleepVM.queuedEpisodes` is currently showing — the signal that owes
    /// `queueCard` a refetch (H1 follow-up, PR #19 review). `nil` (no status
    /// snapshot yet) never triggers a reconcile — `queueCount` already falls
    /// back to `loadedQueuedCount` in that case, so there is nothing to
    /// disagree with. Pulled out as a pure function, mirroring `queueCount`
    /// above, so the trigger condition is unit-testable without a view.
    static func queueNeedsReconcile(liveUnprocessed: Int?, loadedQueuedCount: Int) -> Bool {
        guard let liveUnprocessed else { return false }
        return liveUnprocessed != loadedQueuedCount
    }

    private var queueCard: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            HStack(spacing: CicadaTheme.spacingSM) {
                Text("EPISODES QUEUED (\(Self.queueCount(status: store.status.value, fallback: sleepVM.queuedEpisodes.count)))")
                    .font(.system(size: 10, weight: .semibold, design: .monospaced))
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .tracking(1.2)
                Spacer()
                Button {
                    withAnimation(.easeInOut(duration: 0.18)) {
                        sortAscending.toggle()
                    }
                } label: {
                    Image(systemName: sortAscending
                          ? "arrow.up"
                          : "arrow.down")
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .frame(width: 18, height: 18)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.cicadaPlain)
                .help(sortAscending ? "Oldest first" : "Newest first")

                Button {
                    Task { @MainActor in await sleepVM.load() }
                } label: {
                    Image(systemName: "arrow.clockwise")
                        .font(.system(size: 11))
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .frame(width: 18, height: 18)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.cicadaPlain)
                .help("Refresh queue")
            }

            if sleepVM.queuedEpisodes.isEmpty {
                Text("No episodes queued. Capture a conversation to get started.")
                    .font(.system(size: 12))
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .padding(.vertical, CicadaTheme.spacingSM)
            } else {
                LazyVStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                    ForEach(sortedQueuedEpisodes) { item in
                        EpisodeRow(item: item)
                    }
                }
            }

            if !sleepVM.processedEpisodes.isEmpty {
                Divider().background(CicadaTheme.border).padding(.vertical, CicadaTheme.spacingXS)
                Text("RECENTLY PROCESSED")
                    .font(.system(size: 10, weight: .semibold, design: .monospaced))
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .tracking(1.2)
                LazyVStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                    ForEach(sortedProcessedEpisodes.prefix(10)) { item in
                        EpisodeRow(item: item)
                            .opacity(0.6)
                    }
                }
            }
        }
        .padding(CicadaTheme.spacingLG)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard()
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

// MARK: - Episode Row

private struct EpisodeRow: View {
    let item: EpisodeQueueItem

    var body: some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
            Circle()
                .fill(item.processed ? CicadaTheme.textTertiary : CicadaTheme.accent)
                .frame(width: 8, height: 8)
                .padding(.top, 6)

            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: CicadaTheme.spacingSM) {
                    Text(item.title ?? item.id)
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .lineLimit(1)

                    Text(item.source)
                        .font(.system(size: 9, design: .monospaced))
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .padding(.horizontal, 5)
                        .padding(.vertical, 2)
                        .background(CicadaTheme.surfaceHover)
                        .clipShape(Capsule())

                    Spacer()

                    Text(shortTimestamp(item.timestamp))
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundStyle(CicadaTheme.textTertiary)
                }

                if !item.preview.isEmpty {
                    Text(item.preview)
                        .font(.system(size: 11))
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .lineLimit(2)
                }
            }
        }
        .padding(.horizontal, CicadaTheme.spacingMD)
        .padding(.vertical, CicadaTheme.spacingSM)
        .background(CicadaTheme.surfaceHover.opacity(0.35))
        .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
    }

    private func shortTimestamp(_ raw: String) -> String {
        guard !raw.isEmpty else { return "—" }
        // Accept both ISO-8601 and plain dates; fall back to raw on parse failure.
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = formatter.date(from: raw) {
            return Self.display.string(from: date)
        }
        formatter.formatOptions = [.withInternetDateTime]
        if let date = formatter.date(from: raw) {
            return Self.display.string(from: date)
        }
        return String(raw.prefix(16))
    }

    private static let display: DateFormatter = {
        let f = DateFormatter()
        // Include the year — the queue can span multiple years after a bulk
        // import and a bare "Nov 3" is ambiguous without it.
        f.dateFormat = "MMM d, yyyy HH:mm"
        return f
    }()
}
