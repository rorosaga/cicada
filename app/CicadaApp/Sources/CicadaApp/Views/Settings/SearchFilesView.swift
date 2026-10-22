import SwiftUI

/// Settings → Search & memory (owner, 2026-10-14): *What Cicada can look through*. One place for the folders Cicada
/// keeps (G133, moved from Integrations → Notes & files) and for how well search understands what it finds (moved from
/// Memory → Search model and the Looks page), in plain words — the owner: "without mentioning embeddings".
///
/// **Anatomy (REVIEW §2.2).** One column of grouped cards on `bgFocus` (DR-37), each under a `SectionLabel` (DR-20):
/// 1. *Folders* — one row per folder, its depth as a `Tag` (DR-44), *Manage* a `NeutralButton`; *Add a folder* last.
///    On an empty list *Add a folder…* is the page's one `PrimaryActionButton` (DR-40); otherwise nothing is primary.
/// 2. *How search understands* — two consent rows, each one button that names what it does, the size stated in the
///    detail before the click (network rail): *Understand what you mean* (the sharper version: download, then switch)
///    and *Understand images* (its own second click, dimmed at 45 % with the reason in `.help` until the first is on,
///    DR-41). A failure leads with one `warning` glyph and is never `danger` text (DR-7).
/// 3. One privacy line (`metaFont`).
///
/// **No Advanced (settings defaults, owner 2026-10-22).** The *Search version* picker (raw version names, the larger
/// version's account sheet) and *Rebuild search* left the page: *Understand what you mean* is the one choice, a
/// version already chosen keeps being used, and the index rebuilds itself (derived and disposable). Both stay on the
/// command line (`cicada index use <model>`, `cicada index install <model>`, `cicada index rebuild`).
///
/// **Rails.** Every download is the person's click (`POST /embeddings/install`), never the page's; the app reads folders and the backend parses bytes
/// (`AddFolderRow` → `NSOpenPanel` → `LocalSourceWatcher`); *Look inside* comes before a folder joins memory
/// (`AddFolderSheet`); while Sleep runs a switch waits and the button says why (`ProjectWriteGate.sleepRunning`).
/// `GET /embeddings` is not a Store domain: read when the page opens, polled while a download or re-read runs.
/// Since D6 it is a group on Privacy & data, not a page (`SettingsSection.retired["searchFiles"]`).
struct SearchFilesView: View {
    @Environment(Store.self) private var store
    @State private var embeddings: EmbeddingsStatus?
    @State private var loadFailed = false
    @State private var meaningNote: String?
    @State private var imagesNote: String?
    @State private var acting = false

    private var sleeping: Bool { ProjectWriteGate.sleepRunning(store.status.value) }

    var body: some View {
        // D6: one group on Privacy & data — "Search runs on this Mac" and the sharper-model download. The folders are
        // sources now (the Sources page); Memory's fade card shows only when it holds a suggestion or a chosen pace.
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            understandGroup
            FadePaceCard()
                .settingsRow(.memoryGroup)
        }
        .task { await loadEmbeddings() }
        // Polls only while a download or the background re-read runs; the id flips when it ends, which cancels it.
        .task(id: embeddings?.isBusy == true) { await pollWhileBusy() }
    }

    // MARK: How search understands

    private var understandGroup: some View {
        SettingsGroupCard {
            let meaning = SearchUnderstanding.meaning(embeddings, sleeping: sleeping)
                ?? (loadFailed ? UnderstandRow(detail: Copy.SearchFiles.loadFailed, failed: true) : nil)
            SettingsRow(.searchMeaning, title: Copy.SearchFiles.runsHere, detail: plainDetail(meaning, note: meaningNote)) {
                consentControl(meaning)
            } below: {
                consentBelow(meaning, note: meaningNote, title: Copy.SearchFiles.meaningTitle)
            }
            if let images = SearchUnderstanding.images(embeddings) {
                SettingsDivider()
                SettingsRow(.searchImages, title: Copy.SearchFiles.imagesTitle, detail: plainDetail(images, note: imagesNote)) {
                    consentControl(images)
                } below: {
                    consentBelow(images, note: imagesNote, title: Copy.SearchFiles.imagesTitle)
                }
            }
        }
    }

    /// The detail line in words, unless it is a failure — then it is drawn below with its `warning` glyph (DR-7).
    private func plainDetail(_ row: UnderstandRow?, note: String?) -> String? {
        note != nil || row?.failed == true ? nil : row?.detail
    }

    /// One button that names what it does (or "On"), or a small spinner while a step has no byte count.
    @ViewBuilder
    private func consentControl(_ row: UnderstandRow?) -> some View {
        if let row {
            if let button = row.button, let action = row.action {
                NeutralButton(title: button, size: .compact, isDisabled: !row.enabled || acting,
                              help: row.help, disabledHelp: row.help) { perform(action) }
            } else if row.on {
                Text(Copy.SearchFiles.on)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            } else if row.busy, row.total == 0 {
                ProgressView().controlSize(.small)
            }
        }
    }

    /// A failure's sentence, and the native linear bar while bytes stream.
    @ViewBuilder
    private func consentBelow(_ row: UnderstandRow?, note: String?, title: String) -> some View {
        if note != nil || row?.failed == true, let text = note ?? row?.detail {
            WarningLine(text: text, warning: true)
        }
        if let row, row.busy, row.total > 0 {
            ProgressView(value: Double(min(row.done, row.total)), total: Double(row.total))
                .progressViewStyle(.linear)
                .controlSize(.small)
                .accessibilityLabel(title)
        }
    }

    private func perform(_ action: UnderstandAction) {
        acting = true
        Task { @MainActor in
            defer { acting = false }
            do {
                switch action {
                case .fetchMeaning(let id):
                    meaningNote = nil
                    // One click means "use it": a choice that would keep the sharper version off is cleared first,
                    // so the re-read the download ends with moves search to it.
                    if let choice = embeddings?.choice, choice != id {
                        embeddings = try await APIClient.shared.chooseEmbeddingModel(nil)
                    }
                    embeddings = try await APIClient.shared.installEmbeddingModel(id)
                case .chooseMeaning(let id):
                    meaningNote = nil
                    embeddings = try await APIClient.shared.chooseEmbeddingModel(id)
                case .fetchImages:
                    imagesNote = nil
                    try await APIClient.shared.installImageModel()
                    embeddings = try await APIClient.shared.fetchEmbeddings()
                }
            } catch {
                // The backend's own sentence (`detail`): Sleep running, a download already going, an unsupported Mac.
                let sentence = AddSourceSheet.friendlyError(error)
                if action == .fetchImages { imagesNote = sentence } else { meaningNote = sentence }
                if let fresh = try? await APIClient.shared.fetchEmbeddings() { embeddings = fresh }
            }
        }
    }

    // MARK: Loading

    private func loadEmbeddings() async {
        do {
            embeddings = try await APIClient.shared.fetchEmbeddings()
            loadFailed = false
        } catch {
            loadFailed = true
        }
    }

    private func pollWhileBusy() async {
        guard embeddings?.isBusy == true else { return }
        while !Task.isCancelled {
            try? await Task.sleep(for: SearchModelLogic.pollInterval)
            guard !Task.isCancelled else { return }
            guard let status = try? await APIClient.shared.fetchEmbeddings() else { continue }
            embeddings = status
            if !status.isBusy { return }
        }
    }
}

/// The watched folders, as one group (the folder list and *Add a folder*). It left Settings with D6 — folders are a
/// source — and is kept whole for the Sources page's *This Mac* group to embed; until then each folder is a source row
/// on the Sources page and *Add a source* adds one.
struct WatchedFoldersGroup: View {
    @Environment(Store.self) private var store
    private var inDemo: Bool { DemoMode.isShowing(store.banks.value, bank: store.bank) }
    private var folderChannels: [SourceChannel]? {
        store.channels.value.map { $0.filter { $0.id.hasPrefix("folder:") } }
    }


    var body: some View {
        SettingsGroupCard(header: Copy.SearchFiles.foldersGroup) {
            let demoReason = inDemo ? Copy.SearchFiles.addFolderDemoHelp : nil
            if let folders = folderChannels {
                if folders.isEmpty {
                    AddFolderRow.empty(disabledReason: demoReason)
                } else {
                    ForEach(folders) { channel in
                        FolderChannelRow(channel: channel)
                        SettingsDivider()
                    }
                    addRow(disabledReason: demoReason)
                }
            } else if let error = store.domainErrors[.channels] {
                WarningLine(text: error, warning: true)
                    .padding(CicadaTheme.spacingMD)
            } else {
                HStack(spacing: CicadaTheme.spacingSM) {
                    ProgressView().controlSize(.small)
                    Text(Copy.SearchFiles.checkingFolders)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
                .padding(CicadaTheme.spacingMD)
            }
        }
        .settingsRow(.searchFolders)
    }

    private func addRow(disabledReason: String?) -> AddFolderRow {
        var row = AddFolderRow.folder
        row.disabledReason = disabledReason
        return row
    }

}
