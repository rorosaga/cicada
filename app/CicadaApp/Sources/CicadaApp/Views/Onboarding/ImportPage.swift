import AppKit
import SwiftUI
import UniformTypeIdentifiers

/// F-02 (G145; owner decisions 2 and 3) — *Bring in what you have*. The "Private by design" banner first, then the
/// categories of `ImportCatalog` (Browsers first), then *Your chat history*: the window's one drop target pictured,
/// the exports that arrived, and "No export yet? Ask for one" with *See how* per provider. A tick starts that source
/// at once (`onTick`, R-OB2); its row is the one projection (`SetupProgress`, R-OB4) with an × only where the run can
/// stop (R-OB10) and "Last synced …" when done. Nothing is pre-ticked (R-OB6), nothing is read or counted before a
/// tick (R-IB12). DR-13 (no text on paint), DR-44, DR-48, DR-52, DR-58, DR-67.
struct ImportPage: View {
    let entries: [ImportEntry]
    let snapshots: [FoundItemID: SetupRowSnapshot]
    let browsers: BrowserInventory
    let memoryRoot: String?
    let columnWidth: CGFloat
    let dropTargeted: Bool
    let onTick: (ImportEntry, Bool) -> Void
    let onSeeHow: (ChatVendor) -> Void

    @Environment(IntakeRouter.self) private var intake
    @Environment(SyncActivity.self) private var activity
    @Environment(BrowserWatcher.self) private var watcher
    @Environment(ExportWaitStore.self) private var waits
    @Environment(Store.self) private var store
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var revealed = false

    var body: some View {
        let groups = ImportCatalog.grouped(entries)
        let two = OnboardingLayout.importColumns(columnWidth: columnWidth, scale: CGFloat(CicadaTheme.uiScale)) == 2
        TimelineView(.periodic(from: .now, by: SourceRowText.refreshInterval)) { context in
            VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                ImportPrivacyBanner(memoryRoot: memoryRoot)
                OnboardingHeadline(title: Copy.importTitle, subline: Copy.importSubline)
                if let browsersGroup = groups.first(where: { $0.category == .browsers }) {
                    category(browsersGroup.category, browsersGroup.entries, now: context.date) {
                        BrowsersUnsupportedNote(inventory: browsers)
                    }
                }
                let rest = groups.filter { $0.category != .browsers }
                if two {
                    HStack(alignment: .top, spacing: CicadaTheme.spacingLG) {
                        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                            ForEach(rest.filter { $0.category != .voiceAndMeetings }) {
                                category($0.category, $0.entries, now: context.date) { EmptyView() }
                            }
                        }
                        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                            ForEach(rest.filter { $0.category == .voiceAndMeetings }) {
                                category($0.category, $0.entries, now: context.date) { EmptyView() }
                            }
                            chatHistory(now: context.date)
                        }
                    }
                } else {
                    ForEach(rest) { category($0.category, $0.entries, now: context.date) { EmptyView() } }
                    chatHistory(now: context.date)
                }
            }
        }
        .onAppear { revealed = true }
    }

    // MARK: A category

    private func category<Trailing: View>(_ category: ImportCategory, _ rows: [ImportEntry], now: Date,
                                          @ViewBuilder trailing: () -> Trailing) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            HStack {
                SectionLabel(category.title(entries: entries))
                Spacer(minLength: CicadaTheme.spacingSM)
                trailing()
            }
            VStack(alignment: .leading, spacing: 2) {
                ForEach(Array(rows.enumerated()), id: \.element.id) { index, entry in
                    ImportSourceRow(entry: entry, snapshot: snapshots[entry.id], now: now, onTick: onTick)
                        .padding(.leading, entry.parent == nil ? 0 : CicadaTheme.scaled(28))
                        .opacity(revealed ? 1 : 0)
                        .animation(CicadaMotion.reveal(index: index, reduceMotion: reduceMotion), value: revealed)
                }
                if category == .notesAndFiles {
                    ForEach(folderChannels) { channel in
                        SourceRow(model: SourceRowModel(id: channel.id, origin: "folder", title: channel.label,
                                                        line: SourceRowText.countLine(channel),
                                                        status: SourceRowText.status(channel: channel,
                                                                                     watch: watcher.state(for: channel.id),
                                                                                     run: activity.run(for: channel.id))),
                                  now: now)
                    }
                    AddFolderRow.folder
                }
            }
            .padding(CicadaTheme.spacingSM)
            .background(CicadaTheme.bgFocus, in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
            .ringed(in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
        }
    }

    /// Folders added from this page (G133): shown as they sync; managed in Settings → Integrations.
    private var folderChannels: [SourceChannel] {
        (store.channels.value ?? []).filter { $0.id.hasPrefix(ChannelActions.folderPrefix) }
    }

    // MARK: Your chat history

    private func chatHistory(now: Date) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            SectionLabel(Copy.gsChatHistory)
            dropZone
            // A drop starts the moment it is staged (R-OB2), so only the instant before its row exists shows here.
            ForEach(intake.welcomeDrops.filter { snapshots[.dropped($0.id)] == nil }) { drop in stagedRow(drop) }
            ForEach(droppedSnapshots) { snapshot in
                SourceRow(model: snapshot.model, now: now)
            }
            if let error = intake.welcomeDropError {
                Text(error).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.danger)
                    .fixedSize(horizontal: false, vertical: true)
            }
            SectionLabel(Copy.welcomeAskForOne).padding(.top, CicadaTheme.spacingSM)
            VStack(alignment: .leading, spacing: 2) {
                ForEach(ChatVendor.allCases) { vendor in providerRow(vendor) }
            }
            .padding(CicadaTheme.spacingSM)
            .background(CicadaTheme.bgFocus, in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
            .ringed(in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
            // R-IB22 — each export being waited on, in words that need no notification permission.
            ForEach(waits.active(bank: store.bank)) { wait in
                HStack(spacing: CicadaTheme.spacingXS) {
                    VendorMark(origin: ChatVendor(rawValue: wait.vendor)?.origin, size: CicadaTheme.scaled(14))
                    Text(ExportWaits.rowLine(wait, now: now)).font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
            }
        }
    }

    private var droppedSnapshots: [SetupRowSnapshot] {
        snapshots.values.filter { if case .dropped = $0.id { return true }; return false }
            .sorted { $0.id.key < $1.id.key }
    }

    /// A picture of where to drop: the window has one drop target and the router stages what lands (R-IB15). Lit
    /// while a file hovers, in neutrals (DR-13: nature tokens are for art, not a state).
    private var dropZone: some View {
        let shape = CicadaTheme.shape(CicadaTheme.cornerRadiusSmall)
        return HStack(alignment: .top, spacing: CicadaTheme.spacingSM) {
            Image(systemName: "tray.and.arrow.down").foregroundStyle(CicadaTheme.textSecondary)
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: CicadaTheme.spacingXS) {
                    Text(Copy.importDropLead).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textPrimary)
                    TextButton(title: Copy.intakeChooseFile, inline: true) { Self.chooseFile(intake) }
                }
                Text(Copy.importDropDetail).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
            }
            Spacer(minLength: CicadaTheme.spacingSM)
            HStack(spacing: CicadaTheme.spacingXS) {
                ForEach(ChatVendor.allCases) { VendorMark(vendor: $0, size: CicadaTheme.scaled(16)) }
            }
        }
        .padding(CicadaTheme.spacingMD)
        .background(dropTargeted ? CicadaTheme.bgSelected : Color.clear, in: shape)
        .overlay(shape.strokeBorder(dropTargeted ? CicadaTheme.textSecondary : CicadaTheme.border,
                                    style: StrokeStyle(lineWidth: 1, dash: [6, 4])))
        .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: dropTargeted)
    }

    /// Staged and not yet started (only for the moment between a sniff and its start): ✕ un-stages it.
    private func stagedRow(_ drop: WelcomeDrop) -> some View {
        let title = IntakeSummary.previewTitle(drop.preview)
        return SourceRow(model: SourceRowModel(id: drop.id, origin: drop.preview.origin ?? "", title: title,
                                               line: IntakeSummary.countsLine(drop.preview), status: .idle)) {
            IconButton(systemName: "xmark", help: Copy.welcomeRemoveDrop,
                       accessibilityLabel: "\(Copy.welcomeRemoveDrop), \(title)") { intake.removeWelcomeDrop(drop.id) }
        }
    }

    private func providerRow(_ vendor: ChatVendor) -> some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            VendorMark(vendor: vendor, size: CicadaTheme.scaled(16))
            Text(vendor.title).font(CicadaTheme.font(size: 13, weight: .medium)).foregroundStyle(CicadaTheme.textPrimary)
            Text(Copy.importWait(vendor)).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
            Spacer(minLength: CicadaTheme.spacingSM)
            TextButton(title: Copy.importSeeHow) { onSeeHow(vendor) }
        }
        .frame(minHeight: CicadaTheme.scaled(RowMetrics.oneLine))
        .padding(.horizontal, CicadaTheme.scaled(10))
    }

    /// The same panel the old Welcome ran (`WelcomeChecklist.chooseFile`, moved here with it): the URLs go to the one
    /// intake, which stages them while onboarding shows (R-IB15). ⌘⇧I lands here too (`welcomeChooseRequest`).
    static func chooseFile(_ intake: IntakeRouter) {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.zip, .json, .html, .folder, .commaSeparatedText, .plainText, .xml, .propertyList]
        panel.allowsMultipleSelection = true
        panel.canChooseDirectories = true
        panel.message = Copy.intakeDropTitle
        guard panel.runModal() == .OK else { return }
        intake.accept(urls: panel.urls, from: .welcome)
    }
}

/// F-02's "Private by design" banner: the promise is read in full or it is not made. Laid out as one row (title,
/// sentence and *Show in Finder* side by side), the live pass saw the title wrap to three lines and the sentence cut
/// mid-word at the column's real width. The title now sits over its sentence, and *Show in Finder* trails them only
/// while both read as one line each (`ViewThatFits` measures, so ⌘+ and a narrow window need no width threshold);
/// otherwise it drops under the text, which wraps and never truncates. DR-16, DR-40, DR-70.
struct ImportPrivacyBanner: View {
    let memoryRoot: String?

    var body: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: CicadaTheme.spacingSM) {
                glyph
                words
                Spacer(minLength: CicadaTheme.spacingSM)
                showInFinder
            }
            HStack(alignment: .top, spacing: CicadaTheme.spacingSM) {
                glyph
                VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                    words
                    showInFinder
                }
                Spacer(minLength: 0)
            }
        }
        .padding(CicadaTheme.spacingMD)
        .background(CicadaTheme.bgFocus, in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
        .ringed(in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
        .privacySensitive()
    }

    private var glyph: some View {
        Image(systemName: "laptopcomputer").foregroundStyle(CicadaTheme.textSecondary)
    }

    private var words: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(Copy.importPrivateLead).font(CicadaTheme.font(size: 13, weight: .medium))
                .foregroundStyle(CicadaTheme.textPrimary)
                .fixedSize(horizontal: false, vertical: true)
            Text(Copy.importPrivateTail).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private var showInFinder: some View {
        TextButton(title: Copy.showInFinder) {
            if let memoryRoot { NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: memoryRoot)]) }
        }
        .disabled(memoryRoot == nil)
    }
}

/// One Import row: its control (a checkbox that starts it, or a ✓ for a finished one-time read), the one `SourceRow`,
/// and — for a browser macOS hid — the Full Disk Access fix under it (R-D6).
struct ImportSourceRow: View {
    let entry: ImportEntry
    let snapshot: SetupRowSnapshot?
    let now: Date
    let onTick: (ImportEntry, Bool) -> Void

    @Environment(SyncActivity.self) private var activity
    @Environment(BrowserWatcher.self) private var watcher

    var body: some View {
        let control = ImportRows.control(entry, phase: snapshot?.phase)
        let runKey = GettingStartedSourceRows.runKey(entry.id)
        VStack(alignment: .leading, spacing: 2) {
            HStack(spacing: CicadaTheme.spacingSM) {
                switch control {
                case .tick(let on):
                    Toggle(entry.title, isOn: Binding(get: { on }, set: { onTick(entry, $0) }))
                        .toggleStyle(.checkbox)
                        .labelsHidden()
                        .help(on && entry.keepsUp ? Copy.importUntickHelp : Copy.importTickHelp)
                case .locked:
                    Toggle(entry.title, isOn: .constant(true))
                        .toggleStyle(.checkbox)
                        .labelsHidden()
                        .disabled(true)
                        .help(Copy.importLockedHelp)
                case .done:
                    Image(systemName: "checkmark")
                        .font(CicadaTheme.font(size: 12, weight: .semibold))
                        .foregroundStyle(CicadaTheme.success)
                        .help(Copy.importDoneOnce)
                        .accessibilityLabel(Copy.importDoneOnce)
                }
                SourceRow(model: ImportRows.model(entry, snapshot: snapshot), now: now,
                          onCancel: snapshot?.cancellable == true
                              ? runKey.map { key -> () -> Void in { activity.cancel(key) } } : nil)
            }
            if case .browser(let channel) = entry.id, watcher.state(for: channel) == .blocked,
               let error = watcher.error(for: channel) {
                FullDiskAccessHint(error: error)
            }
            if case .failed(let why)? = snapshot?.row.state {
                Text(why).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.warning)
                    .fixedSize(horizontal: false, vertical: true)
            }
            // R-OB7 — before the grant: say what the tick will do (the design's "Needs Full Disk Access · Allow…").
            if case .needsAction? = snapshot?.row.state, case .browser = entry.id {
                Text(Copy.importNeedsAccess).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}
