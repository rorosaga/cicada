import SwiftUI

/// Settings → Memory (G139): the derived search index and the link backfill,
/// both user-started and both refused with a plain sentence while Sleep runs.
/// Rebuilding the index costs CPU, never a fact (TODO ruling 3), which is why
/// it can sit behind one button with no confirmation. Below them sits G147's
/// *How things fade* (`FadePaceCard`) — suggestions from the person's own decay
/// answers, applied only on Apply.
///
/// "Look for duplicates" is deliberately absent (R-O17): the dedup endpoint
/// blocks the event loop, its dry run never reaches the Inbox, and its live
/// run leaves uncommitted merges for the next `git add -A` writer (the G85
/// smear). `CicadaPagesTests.testNoPageCallsTheDedupSweep` holds that line.
///
/// G182 phase 3 — *Search model* shares the Search index's card (DR-37: a group, never a one-line
/// card of its own): a `PillPicker` of the backend's catalog labels, the detail line in words
/// (`SearchModelLogic.detail`), and a model not on this Mac yet routed to `LargerSearchModelSheet`
/// instead of switching (`SearchModelLogic.route`). While Sleep writes the picker is disabled at 45 %
/// with the reason in `.help` (DR-41), for the whole run (`ProjectWriteGate.sleepRunning`): the server
/// refuses a switch while any run goes, since a drain re-syncs the index between its batches. No monospace anywhere on the row (DR-19).
struct MemoryView: View {
    @Environment(Store.self) private var store
    @State private var index: SearchIndexStatus?
    @State private var indexNote: String?
    @State private var linksNote: String?
    @State private var busy = false
    @State private var embeddings: EmbeddingsStatus?
    @State private var modelNote: String?
    @State private var choosing = false
    @State private var installModelID: String?
    @State private var showInstall = false

    var body: some View {
        SettingsPage(section: .memory) {
            SettingsGroupCard {
                SettingsRow(.searchIndex, title: Copy.searchIndexTitle, detail: indexNote ?? MemoryMaintenanceText.index(index)) {
                    Button(Copy.rebuildNow) {
                        run {
                            index = try await APIClient.shared.rebuildSearchIndex()
                            indexNote = nil
                        } onError: { indexNote = $0 }
                    }
                    .disabled(busy)
                }
                SettingsDivider()
                searchModelRow
                SettingsDivider()
                SettingsRow(.enrichLinks, title: Copy.enrichLinksTitle, detail: linksNote ?? Copy.enrichLinksDetail) {
                    Button(Copy.fetchNow) {
                        run {
                            linksNote = MemoryMaintenanceText.links(try await APIClient.shared.enrichLinksNow())
                        } onError: { linksNote = $0 }
                    }
                    .disabled(busy)
                }
            }
            FadePaceCard()
        }
        .task { index = try? await APIClient.shared.fetchSearchIndexStatus() }
        .task { await loadEmbeddings() }
        // Polls only while the larger model installs; the id flips when the install ends, which
        // cancels the loop.
        .task(id: embeddings?.install.isInstalling == true) { await pollWhileInstalling() }
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

    // MARK: Search model (G182 phase 3)

    @ViewBuilder
    private var searchModelRow: some View {
        let sleeping = ProjectWriteGate.sleepRunning(store.status.value)
        SettingsRow(.searchModel, title: Copy.SearchModel.title, detail: modelNote ?? SearchModelLogic.detail(embeddings)) {
            if let embeddings, !embeddings.models.isEmpty {
                PillPicker(title: Copy.SearchModel.title,
                           selection: Binding(get: { embeddings.nextModel }, set: { pick($0) }),
                           options: embeddings.models.map { PillOption(value: $0.id, label: $0.label) })
                    .disabled(sleeping || choosing)
                    .opacity(sleeping ? NeutralButton.disabledOpacity : 1)
                    .help(sleeping ? Copy.SearchModel.sleepRunningHelp : Copy.SearchModel.pickerHelp)
            }
        }
    }

    private func loadEmbeddings() async {
        do {
            embeddings = try await APIClient.shared.fetchEmbeddings()
            modelNote = nil
        } catch {
            modelNote = Copy.SearchModel.loadFailed
        }
    }

    private func pollWhileInstalling() async {
        guard embeddings?.install.isInstalling == true else { return }
        while !Task.isCancelled {
            try? await Task.sleep(for: SearchModelLogic.pollInterval)
            guard !Task.isCancelled else { return }
            guard let status = try? await APIClient.shared.fetchEmbeddings() else { continue }
            embeddings = status
            if !status.install.isInstalling { return }
        }
    }

    private func pick(_ id: String) {
        guard let status = embeddings else { return }
        switch SearchModelLogic.route(picked: id, status: status, sleepWriting: ProjectWriteGate.sleepRunning(store.status.value)) {
        case .nothing:
            break
        case .blocked:
            modelNote = Copy.SearchModel.sleepRunningHelp
        case .install:
            installModelID = id
            showInstall = true
        case .choose(let id):
            choosing = true
            Task { @MainActor in
                defer { choosing = false }
                do {
                    embeddings = try await APIClient.shared.chooseEmbeddingModel(id)
                    modelNote = nil
                } catch {
                    // 409's `detail` is the backend's sentence ("Sleep is running…", "isn't installed…").
                    modelNote = AddSourceSheet.friendlyError(error)
                    if let fresh = try? await APIClient.shared.fetchEmbeddings() { embeddings = fresh }
                }
            }
        }
    }

    /// `work` is `@MainActor` because it assigns this view's `@State` after an
    /// `await` — a plain async closure could resume off the main thread.
    /// A 409 is either Sleep (which writes the same files) or another run of
    /// the same job; both backends say which in their `detail`.
    private func run(_ work: @escaping @MainActor () async throws -> Void,
                     onError: @escaping @MainActor (String) -> Void) {
        busy = true
        Task { @MainActor in
            defer { busy = false }
            do {
                try await work()
            } catch APIError.httpError(409, let message) {
                onError(SleepRefusal.matches(APIError.httpError(409, message)) ? Copy.sleepIsRunning : Copy.alreadyRunning)
            } catch {
                onError(AddSourceSheet.friendlyError(error))
            }
        }
    }
}
