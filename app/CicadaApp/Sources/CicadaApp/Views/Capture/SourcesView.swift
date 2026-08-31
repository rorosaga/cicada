import SwiftUI

/// The Capture page (G62). Shows **only what is actually connected** — one
/// compact row per channel the backend reports as having state — plus the
/// Sleep queue. Everything explanatory (what a channel is, how to export from
/// a vendor, where a bookmarks file lives) lives behind the `+` button in
/// `AddSourceSheet`, so this page stays a status readout rather than a wall
/// of onboarding copy.
///
/// The origins strip that used to live here moved to the Activity page
/// (G68 §1) — "where your memory comes from" is the same provenance question
/// Usage and Contributors answer.
///
/// Every value here is a projection over `Store` snapshots (§5.5): the page
/// renders correct, real data on a cold launch with the backend down.
struct SourcesView: View {
    @Environment(SleepViewModel.self) private var sleepVM
    @Environment(Store.self) private var store

    @State private var showAddSheet = false
    @State private var sheetTile: AddSourceTile?
    @State private var feedback: ChannelFeedback?
    @State private var busyChannel: String?

    // MARK: - Store projections (§5.5)

    private var channels: [SourceChannel] { store.channels.value ?? [] }
    private var connected: [SourceChannel] { SourceChannel.sortedConnected(channels) }
    private var channelsLoading: Bool { store.channels.isEmpty && store.channels.isRefreshing }
    private var status: StatusSnapshot? { store.status.value }
    private var statusLoading: Bool { store.status.isEmpty && store.status.isRefreshing }

    var body: some View {
        VStack(spacing: 0) {
            PageHeader(
                title: "Capture",
                subtitle: "What Cicada reads from. Add a source with +."
            ) {
                addButton
            }

            ScrollView {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                    connectedCard
                    queueCard
                }
                .padding(.horizontal, CicadaTheme.spacingXL)
                .padding(.bottom, CicadaTheme.spacingXXL)
            }
        }
        .background(CicadaTheme.background)
        .onChange(of: sleepVM.isRunning) { _, running in
            if !running { Task { await store.refresh([.status, .channels]) } }
        }
        // ⌘N while the Capture page is on screen opens the picker. Hidden-button
        // pattern, same as ContentView's ⌘K.
        .background {
            Button("") { openSheet(nil) }
                .keyboardShortcut("n", modifiers: .command)
                .buttonStyle(.plain)
                .frame(width: 0, height: 0)
                .opacity(0)
        }
        .sheet(isPresented: $showAddSheet) {
            AddSourceSheet(initialTile: sheetTile) { showAddSheet = false }
        }
    }

    private var addButton: some View {
        Button { openSheet(nil) } label: {
            Image(systemName: "plus")
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(.white)
                .frame(width: 28, height: 28)
                .background(Circle().fill(CicadaTheme.accent))
        }
        .buttonStyle(.plain)
        .help("Add a source (⌘N)")
        .accessibilityLabel("Add a source")
    }

    private func openSheet(_ tile: AddSourceTile?) {
        feedback = nil
        sheetTile = tile
        showAddSheet = true
    }

    // MARK: - Connected

    @ViewBuilder
    private var connectedCard: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            sectionLabel("CONNECTED")

            if channelsLoading && channels.isEmpty {
                HStack(spacing: CicadaTheme.spacingSM) {
                    ProgressView().controlSize(.small)
                    Text("Checking your sources…")
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
            } else if connected.isEmpty {
                emptyState
            } else {
                VStack(spacing: 2) {
                    ForEach(connected) { channel in
                        ConnectedChannelRow(channel: channel, isBusy: busyChannel == channel.id) { action in
                            handle(action, for: channel)
                        }
                    }
                }
                if let feedback {
                    Text(feedback.text)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(feedback.isError ? CicadaTheme.danger : CicadaTheme.success)
                        // Clears itself after 5 s. Keyed on the value, so a
                        // second result restarts the timer instead of
                        // inheriting the first one's remaining time.
                        .task(id: feedback) {
                            try? await Task.sleep(for: .seconds(5))
                            guard !Task.isCancelled else { return }
                            self.feedback = nil
                        }
                }
            }
        }
        .padding(CicadaTheme.spacingLG)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard()
    }

    private var emptyState: some View {
        VStack(spacing: CicadaTheme.spacingSM) {
            Image(systemName: "tray")
                .font(.system(size: 26))
                .foregroundStyle(CicadaTheme.textTertiary)
            Text("Nothing connected yet")
                .font(CicadaTheme.headingFont)
                .foregroundStyle(CicadaTheme.textPrimary)
            Text("Add a chat export, bookmarks, a feed or a calendar.")
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .multilineTextAlignment(.center)
            addButton.padding(.top, CicadaTheme.spacingXS)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, CicadaTheme.spacingXL)
    }

    private func handle(_ action: String, for channel: SourceChannel) {
        feedback = nil
        switch action {
        case "poll":
            Task { await run(channel) { try await Self.poll(channel) } }
        case "sync":
            Task { await run(channel) { try await Self.sync(channel) } }
        default:
            openSheet(AddSourceTile.forChannel(channel.id))
        }
    }

    private func run(_ channel: SourceChannel, _ work: @escaping () async throws -> String) async {
        busyChannel = channel.id
        do {
            feedback = ChannelFeedback(text: try await work(), isError: false)
        } catch {
            feedback = ChannelFeedback(text: AddSourceSheet.friendlyError(error), isError: true)
        }
        busyChannel = nil
        await store.refresh([.channels, .status, .sources, .feeds, .calendars])
    }

    private static let fetchDisabledHint =
        "Live fetch is disabled on this backend — set CICADA_ALLOW_FEED_FETCH=1 and restart."

    private static func poll(_ channel: SourceChannel) async throws -> String {
        if channel.id == "calendar" {
            let r = try await APIClient.shared.pollCalendars()
            return r.skippedNoNetwork > 0 ? Self.fetchDisabledHint : "\(r.new) new event(s)"
        }
        let r = try await APIClient.shared.pollFeeds()
        return r.skippedNoNetwork > 0 ? Self.fetchDisabledHint : "\(r.new) new item(s)"
    }

    private static func sync(_ channel: SourceChannel) async throws -> String {
        if channel.id == "notes" {
            let r = try await APIClient.shared.syncNotes()
            return "\(r.new) new · \(r.skipped) unchanged"
        }
        let r = try await APIClient.shared.syncBookmarks()
        return "\(r.new) new · \(r.skipped) already saved"
    }

    // MARK: - Queue

    private var queueCard: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            sectionLabel("QUEUE")

            if statusLoading && status == nil {
                HStack(spacing: CicadaTheme.spacingSM) {
                    ProgressView().controlSize(.small)
                    Text("Checking the queue…")
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
            } else {
                let count = status?.episodes.unprocessed ?? 0
                HStack(alignment: .center, spacing: CicadaTheme.spacingMD) {
                    Image(systemName: count == 0 ? "checkmark.circle" : "tray.full")
                        .font(.system(size: 13, weight: .medium))
                        .foregroundStyle(count == 0 ? CicadaTheme.success : CicadaTheme.accent)
                        .frame(width: 28, height: 28)
                        .background(Circle().fill((count == 0 ? CicadaTheme.success : CicadaTheme.accent).opacity(0.12)))
                        .overlay(Circle().stroke(CicadaTheme.border, lineWidth: 1))

                    VStack(alignment: .leading, spacing: 2) {
                        Text(count == 0
                             ? "All caught up"
                             : "\(count) item\(count == 1 ? "" : "s") queued for the next Sleep cycle")
                            .font(CicadaTheme.headingFont)
                            .foregroundStyle(CicadaTheme.textPrimary)
                        if count > 0 {
                            Text("\(Copy.consolidateNow) to fold them into the graph immediately.")
                                .font(CicadaTheme.captionFont)
                                .foregroundStyle(CicadaTheme.textTertiary)
                        } else if let last = formattedLastSleep {
                            Text("Last consolidated \(last)")
                                .font(CicadaTheme.captionFont)
                                .foregroundStyle(CicadaTheme.textTertiary)
                        }
                    }

                    Spacer()

                    consolidateButton(count: count)
                }

                // A failed trigger used to be visible only on the Sleep page.
                // The button that failed is here, so the reason belongs here.
                if let err = sleepVM.errorMessage ?? sleepVM.lastError, !err.isEmpty {
                    Text(err)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.danger)
                        .frame(maxWidth: .infinity, alignment: .trailing)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
        .padding(CicadaTheme.spacingLG)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard()
    }

    private func consolidateButton(count: Int) -> some View {
        Button {
            Task {
                await sleepVM.triggerManually()
                await store.refresh([.status, .channels])
            }
        } label: {
            HStack(spacing: CicadaTheme.spacingXS) {
                if sleepVM.isRunning {
                    ProgressView().controlSize(.small).frame(width: 12, height: 12)
                } else {
                    Image(systemName: "moon.fill").font(.system(size: 12))
                }
                Text(sleepVM.isRunning ? Copy.consolidating : Copy.consolidateNow)
                    .font(.system(size: 12, weight: .semibold))
            }
            .foregroundStyle(count == 0 && !sleepVM.isRunning ? CicadaTheme.textTertiary : .white)
            .padding(.horizontal, CicadaTheme.spacingLG)
            .padding(.vertical, CicadaTheme.spacingSM)
            .background(count == 0 && !sleepVM.isRunning ? CicadaTheme.surfaceElevated : CicadaTheme.accent.opacity(0.9))
            .clipShape(Capsule())
        }
        .buttonStyle(.plain)
        .disabled(sleepVM.isRunning || count == 0)
        .help(count == 0 ? "Nothing queued right now" : "Run the Sleep cycle now")
        .accessibilityLabel(Copy.consolidateNow)
    }

    private var formattedLastSleep: String? {
        guard let date = StatusSnapshot.parseDate(status?.lastSleepAt) else { return nil }
        let f = DateFormatter()
        f.dateFormat = "MMM d, h:mm a"
        return f.string(from: date)
    }

    // MARK: - Shared

    private func sectionLabel(_ text: String) -> some View {
        Text(text)
            .font(.system(size: 10, weight: .semibold, design: .monospaced))
            .foregroundStyle(CicadaTheme.textTertiary)
            .tracking(1.2)
    }
}
