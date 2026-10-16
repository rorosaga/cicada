import SwiftUI

/// Settings → Search & files (owner, 2026-10-14): *What Cicada can look through*. One place for the folders Cicada
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
/// 4. *Advanced*, collapsed by default and remembered per viewer (DR-39): the *Search version* picker, the larger
///    version's account sheet, *Rebuild search*. Version names live here and nowhere else.
///
/// **Rails.** Every download is the person's click (`POST /embeddings/install`), never the page's; an account key rides
/// one request body and is never kept (`LargerSearchModelSheet`); the app reads folders and the backend parses bytes
/// (`AddFolderRow` → `NSOpenPanel` → `LocalSourceWatcher`); *Look inside* comes before a folder joins memory
/// (`AddFolderSheet`); while Sleep runs a switch waits and the button says why (`ProjectWriteGate.sleepRunning`).
/// `GET /embeddings` is not a Store domain: read when the page opens, polled while a download or re-read runs.
struct SearchFilesView: View {
    @Environment(Store.self) private var store
    @Environment(SettingsFocus.self) private var focus: SettingsFocus?
    /// DR-39 — per viewer, never synced: a person who opened Advanced finds it open next time.
    @AppStorage(Self.advancedKey) private var advancedOpen = false
    @State private var embeddings: EmbeddingsStatus?
    @State private var loadFailed = false
    @State private var meaningNote: String?
    @State private var imagesNote: String?
    @State private var modelNote: String?
    @State private var acting = false
    @State private var index: SearchIndexStatus?
    @State private var indexNote: String?
    @State private var rebuilding = false
    @State private var installModelID: String?
    @State private var showInstall = false
    /// A picked version not on this Mac: the confirm that names its size. Nothing is sent until its *Download*.
    @State private var pendingDownload: String?

    static let advancedKey = "cicada.searchFiles.advancedOpen"

    private var sleeping: Bool { ProjectWriteGate.sleepRunning(store.status.value) }
    private var inDemo: Bool { DemoMode.isShowing(store.banks.value, bank: store.bank) }
    private var folderChannels: [SourceChannel]? {
        store.channels.value.map { $0.filter { $0.id.hasPrefix("folder:") } }
    }

    var body: some View {
        SettingsPage(section: .searchFiles) {
            foldersGroup
            understandGroup
            Text(Copy.SearchFiles.privacyLine)
                .font(CicadaTheme.metaFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.horizontal, CicadaTheme.spacingXS)
            advanced
        }
        .task { await loadEmbeddings() }
        .task { index = try? await APIClient.shared.fetchSearchIndexStatus() }
        // Polls only while a download or the background re-read runs; the id flips when it ends, which cancels it.
        .task(id: embeddings?.isBusy == true) { await pollWhileBusy() }
        .onAppear { openAdvancedIfLanded() }
        .onChange(of: focus?.landedNonce ?? 0) { _, _ in openAdvancedIfLanded() }
        // R-HS16 — a sheet centred on the window, never a popover at the panel's edge.
        .sheet(isPresented: $showInstall) {
            SettingsSheet(title: Copy.SearchModel.sheetTitle, onClose: { showInstall = false }) {
                LargerSearchModelSheet(modelID: installModelID ?? "",
                                       onStarted: { status in
                                           embeddings = status
                                           modelNote = nil
                                           showInstall = false
                                       },
                                       onCancel: { showInstall = false })
            }
        }
    }

    // MARK: Folders

    private var foldersGroup: some View {
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

    // MARK: How search understands

    private var understandGroup: some View {
        SettingsGroupCard(header: Copy.SearchFiles.understandGroup) {
            let meaning = SearchUnderstanding.meaning(embeddings, sleeping: sleeping)
                ?? (loadFailed ? UnderstandRow(detail: Copy.SearchFiles.loadFailed, failed: true) : nil)
            SettingsRow(.searchMeaning, title: Copy.SearchFiles.meaningTitle, detail: plainDetail(meaning, note: meaningNote)) {
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

    // MARK: Advanced (DR-39)

    private var advanced: some View {
        DisclosureGroup(isExpanded: $advancedOpen) {
            SettingsGroupCard {
                searchVersionRow
                SettingsDivider()
                SettingsRow(.searchIndex, title: Copy.SearchFiles.rebuildTitle,
                            detail: indexNote ?? MemoryMaintenanceText.index(index)) {
                    NeutralButton(title: Copy.SearchFiles.rebuildNow, size: .compact, isDisabled: rebuilding) { rebuild() }
                }
            }
            .padding(.top, CicadaTheme.spacingSM)
        } label: {
            Text(Copy.SearchFiles.advanced)
                .font(CicadaTheme.font(size: 13, weight: .medium))
                .foregroundStyle(CicadaTheme.textSecondary)
        }
        .settingsRow(.searchAdvanced)
    }

    /// The catalog's versions by their own labels — the one place they are named. A selection is never the consent
    /// (review B1): a version not on this Mac raises a confirm that names its size, and only its *Download* button
    /// sends; the larger one opens the account sheet. Disabled at 45 % with the reason in `.help` while Sleep writes
    /// (DR-41).
    @ViewBuilder
    private var searchVersionRow: some View {
        SettingsRow(.searchModel, title: Copy.SearchModel.title, detail: modelNote ?? SearchModelLogic.detail(embeddings)) {
            if let embeddings, !embeddings.models.isEmpty {
                PillPicker(title: Copy.SearchModel.title,
                           selection: Binding(get: { embeddings.nextModel }, set: { pick($0) }),
                           options: embeddings.models.map { PillOption(value: $0.id, label: $0.label) })
                    .disabled(sleeping || acting)
                    .opacity(sleeping ? NeutralButton.disabledOpacity : 1)
                    .help(sleeping ? Copy.SearchModel.sleepRunningHelp : Copy.SearchModel.pickerHelp)
            }
        } below: {
            if let id = pendingDownload, let embeddings {
                HStack(spacing: CicadaTheme.spacingSM) {
                    Text(SearchModelLogic.confirmation(for: id, in: embeddings))
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                    Spacer(minLength: CicadaTheme.spacingSM)
                    TextButton(title: Copy.SearchModel.confirmCancel) { pendingDownload = nil }
                    NeutralButton(title: Copy.SearchModel.confirmDownloadButton, size: .compact,
                                  isDisabled: sleeping || acting || embeddings.install.isInstalling,
                                  help: Copy.SearchModel.confirmDownloadHelp,
                                  disabledHelp: sleeping ? Copy.SearchModel.sleepRunningHelp : Copy.SearchFiles.downloadRunningHelp) {
                        confirmDownload(id)
                    }
                }
            }
        }
    }

    /// A pick never downloads (review B1): `.confirmDownload` only raises the confirm.
    private func pick(_ id: String) {
        guard let status = embeddings else { return }
        pendingDownload = nil
        switch SearchModelLogic.route(picked: id, status: status, sleepWriting: sleeping) {
        case .nothing:
            break
        case .blocked:
            modelNote = Copy.SearchModel.sleepRunningHelp
        case .install:
            installModelID = id
            showInstall = true
        case .confirmDownload(let id):
            pendingDownload = id
        case .choose(let id):
            send { try await APIClient.shared.chooseEmbeddingModel(id) }
        }
    }

    /// The confirm's explicit *Download*: the person's click, after the size was said.
    private func confirmDownload(_ id: String) {
        pendingDownload = nil
        send { try await APIClient.shared.installEmbeddingModel(id) }
    }

    private func send(_ work: @escaping @MainActor () async throws -> EmbeddingsStatus) {
        acting = true
        Task { @MainActor in
            defer { acting = false }
            do {
                embeddings = try await work()
                modelNote = nil
            } catch {
                // 409's `detail` is the backend's sentence ("Sleep is running…", "isn't on this Mac yet").
                modelNote = AddSourceSheet.friendlyError(error)
                if let fresh = try? await APIClient.shared.fetchEmbeddings() { embeddings = fresh }
            }
        }
    }

    /// Rebuilding costs CPU, never a fact (TODO ruling 3), so it is one button with no confirmation.
    private func rebuild() {
        rebuilding = true
        Task { @MainActor in
            defer { rebuilding = false }
            do {
                index = try await APIClient.shared.rebuildSearchIndex()
                indexNote = nil
            } catch APIError.httpError(409, let message) {
                indexNote = SleepRefusal.matches(APIError.httpError(409, message)) ? Copy.sleepIsRunning : Copy.alreadyRunning
            } catch {
                indexNote = AddSourceSheet.friendlyError(error)
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

    /// A search for "embedding" or "rebuild" lands on the Advanced disclosure; it opens so the row is on screen.
    private func openAdvancedIfLanded() {
        if focus?.landed == .searchAdvanced { advancedOpen = true }
    }
}
