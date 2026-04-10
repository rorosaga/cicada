import SwiftUI

// MARK: - Sleep Dashboard

struct SleepView: View {
    @Binding var selectedTab: AppTab
    @Environment(SleepViewModel.self) private var sleepVM
    @State private var scheduleDate: Date = Self.defaultDate()
    @State private var scheduleEnabled: Bool = false
    @State private var loadedOnce: Bool = false
    @State private var showUploadOverlay = false
    // Default to descending (newest first) — the common case when reviewing
    // what's about to be consolidated.
    @State private var sortAscending: Bool = false

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
            CicadaTheme.background.ignoresSafeArea()

            ScrollView {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                    headerRow
                    if let error = sleepVM.lastError ?? sleepVM.errorMessage, !error.isEmpty {
                        errorBanner(error)
                    }
                    scheduleCard
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
        .onChange(of: showUploadOverlay) { _, isOpen in
            // When the import overlay closes, refresh the episode queue so
            // newly-uploaded conversations show up immediately.
            if !isOpen {
                Task { @MainActor in await sleepVM.load() }
            }
        }
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
        HStack(alignment: .firstTextBaseline) {
            VStack(alignment: .leading, spacing: 4) {
                Text("Sleep Cycle")
                    .font(CicadaTheme.titleFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                Text("Consolidate today's episodes into the memory graph.")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
            Spacer()
        }
    }

    // MARK: Schedule

    private var scheduleCard: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            Text("SCHEDULE")
                .font(.system(size: 10, weight: .semibold, design: .monospaced))
                .foregroundStyle(CicadaTheme.textTertiary)
                .tracking(1.2)

            Toggle(isOn: Binding(
                get: { scheduleEnabled },
                set: { newValue in
                    scheduleEnabled = newValue
                    commitSchedule()
                }
            )) {
                Text("Auto-run Sleep cycle daily")
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
            }
            .toggleStyle(.switch)

            HStack(spacing: CicadaTheme.spacingMD) {
                Text("At")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                DatePicker(
                    "",
                    selection: Binding(
                        get: { scheduleDate },
                        set: { newDate in
                            scheduleDate = newDate
                            commitSchedule()
                        }
                    ),
                    displayedComponents: .hourAndMinute
                )
                .labelsHidden()
                .disabled(!scheduleEnabled)
                Spacer()
            }

            if scheduleEnabled {
                Text("Next run: \(formattedTime(scheduleDate))")
                    .font(.system(size: 11))
                    .foregroundStyle(CicadaTheme.textSecondary)
            } else {
                Text("Manual triggers only.")
                    .font(.system(size: 11))
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
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
            HStack {
                Text("PROGRESS")
                    .font(.system(size: 10, weight: .semibold, design: .monospaced))
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .tracking(1.2)
                Spacer()
                Button {
                    Task { @MainActor in await sleepVM.triggerManually() }
                } label: {
                    HStack(spacing: CicadaTheme.spacingXS) {
                        Image(systemName: sleepVM.isRunning ? "hourglass" : "play.fill")
                            .font(.system(size: 11))
                        Text(sleepVM.isRunning ? "Running…" : "Run now")
                            .font(.system(size: 12, weight: .medium))
                    }
                    .foregroundStyle(sleepVM.isRunning ? CicadaTheme.textTertiary : CicadaTheme.accent)
                    .padding(.horizontal, CicadaTheme.spacingMD)
                    .padding(.vertical, CicadaTheme.spacingSM)
                }
                .buttonStyle(.plain)
                .glassCard(cornerRadius: CicadaTheme.cornerRadiusSmall)
                .disabled(sleepVM.isRunning)
            }

            ProgressView(value: sleepVM.progressFraction)
                .progressViewStyle(.linear)
                .tint(CicadaTheme.accent)
                .animation(.easeInOut(duration: 0.35), value: sleepVM.progressFraction)

            Text(sleepVM.status?.progress ?? "Idle")
                .font(.system(size: 12))
                .foregroundStyle(CicadaTheme.textSecondary)
                .frame(maxWidth: .infinity, alignment: .leading)

            // Non-fatal warnings (e.g. LEANN episode index rebuild failed
            // even though entity writes + commit succeeded). Surfaced so a
            // "completed with warnings" cycle never looks like a clean pass.
            if let warning = sleepVM.status?.indexWarning, !warning.isEmpty {
                warningBanner(warning)
            }

            HStack(spacing: CicadaTheme.spacingMD) {
                counterChip(label: "Episodes", value: sleepVM.status?.episodesTotal ?? 0)
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

    private func counterChip(label: String, value: Int) -> some View {
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
        }
        .padding(.horizontal, CicadaTheme.spacingMD)
        .padding(.vertical, CicadaTheme.spacingSM)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(CicadaTheme.surfaceHover)
        .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
    }

    // MARK: Queue

    private var queueCard: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            HStack(spacing: CicadaTheme.spacingSM) {
                Text("EPISODES QUEUED (\(sleepVM.queuedEpisodes.count))")
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
                .buttonStyle(.plain)
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
                .buttonStyle(.plain)
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
                .foregroundStyle(Color(hex: 0xF59E0B))
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
        .background(Color(hex: 0xF59E0B).opacity(0.10))
        .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
    }

    // MARK: Error banner

    private func errorBanner(_ text: String) -> some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingSM) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.system(size: 13))
                .foregroundStyle(Color(hex: 0xEF4444))
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
        .background(Color(hex: 0xEF4444).opacity(0.12))
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
