import AppKit
import SwiftUI

/// Shared by the Safari/Chrome flows and the Feed strip's "Sync now" (R1):
/// read the file(s) off-main, POST bytes through `Store.perform`, return the
/// honest one-line result. Throws `BrowserFileError` (with the fix) or the
/// API error.
///
/// `@MainActor` because `Store` is, and — unlike the panels below, which
/// inherit it from `View` — a bare enum gets no isolation inference: without
/// it `store.toast` is an error under Swift 5.10 ("main actor-isolated
/// property referenced from a nonisolated context"). The file reads still
/// happen off-main inside `BrowserFileReader.read`'s detached task.
enum BrowserImportActions {
    @MainActor
    static func syncChannel(_ id: String, store: Store) async throws -> String {
        switch id {
        case "safari-tabs":
            let db = try await BrowserFileReader.read(.safariTabsDb)
            let wal = try await BrowserFileReader.readIfPresent(.safariTabsWal)
            let m = SyncSafariTabs(db: db, wal: wal, devices: nil)
            guard await store.perform(m), let r = m.result else { throw ImportActionError.failed(store.toast ?? "Sync failed") }
            return BrowserImportSummary.tabs(r)
        case "safari-bookmarks":
            let data = try await BrowserFileReader.read(.safariBookmarks)
            let m = SyncBrowserBookmarks(chromeData: nil, safariData: data, folders: nil)
            guard await store.perform(m), let r = m.result else { throw ImportActionError.failed(store.toast ?? "Sync failed") }
            return BrowserImportSummary.bookmarks(r)
        case "chrome-bookmarks":
            let data = try await BrowserFileReader.read(.chromeBookmarks)
            let m = SyncBrowserBookmarks(chromeData: data, safariData: nil, folders: nil)
            guard await store.perform(m), let r = m.result else { throw ImportActionError.failed(store.toast ?? "Sync failed") }
            return BrowserImportSummary.bookmarks(r)
        default:
            throw ImportActionError.failed("Unknown channel \(id)")
        }
    }

    enum ImportActionError: Error, LocalizedError {
        case failed(String)
        var errorDescription: String? { if case .failed(let m) = self { return m }; return nil }
    }
}

/// The Full-Disk-Access fix, shown exactly where the read failed (R9). The
/// button only appears for a permission failure — a genuinely missing file
/// has no setting to open.
struct FullDiskAccessHint: View {
    let error: BrowserFileError
    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            Text(error.userMessage)
                .font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.danger)
                .fixedSize(horizontal: false, vertical: true)
            if case .notReadable = error {
                Button("Open Full Disk Access settings") { NSWorkspace.shared.open(BrowserFileError.fullDiskAccessURL) }
                    .buttonStyle(.bordered)
                    .accessibilityLabel("Open System Settings at Full Disk Access")
            }
        }
    }
}

/// Where a browser import is: read → preview → pick → import → done.
enum BrowserImportStage: Equatable {
    case idle, reading, previewing, ready, importing
    case done(String)
    case fileError(BrowserFileError)
    case failed(String)
}

/// Safari: two sub-flows on one panel — bookmark folders and iCloud tabs —
/// each with its own preview, selection and result. Reads happen on
/// appear so the counts are visible before any decision.
struct SafariImportPanel: View {
    @State private var picked: Sub = .bookmarks
    enum Sub: String, CaseIterable, Identifiable { case bookmarks, tabs; var id: String { rawValue } }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            Picker("Import", selection: $picked) {
                Text("Bookmarks & Reading List").tag(Sub.bookmarks)
                Text("iCloud tabs").tag(Sub.tabs)
            }
            .pickerStyle(.segmented)
            .accessibilityLabel("Choose what to import from Safari")
            switch picked {
            case .bookmarks: BookmarkFolderPanel(browser: .safari)
            case .tabs: SafariTabsPanel()
            }
        }
    }
}

/// Device picker for iCloud tabs. The preview is fetched on appear (the
/// bytes are read once and re-posted on Import — the backend caches nothing,
/// R1); devices with zero tabs are shown but cannot be ticked.
struct SafariTabsPanel: View {
    @Environment(Store.self) private var store
    @State private var stage: BrowserImportStage = .idle
    @State private var preview: SafariTabsPreview?
    @State private var selected: Set<String> = []
    @State private var bytes: (db: Data, wal: Data?)?
    /// The in-flight read/preview/import. Cancelled — not just abandoned —
    /// on disappear or a newer `load()`, the same rule `AddSourceSheet`
    /// applies to its import task (G71 fix round 1, H1): a late response
    /// must not land on a panel the user has since left.
    @State private var task: Task<Void, Never>?

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            Text("Every tab open in Safari on your other devices, as iCloud last synced them. Only tabs Cicada hasn't saved become new items.")
                .font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            switch stage {
            case .idle, .reading, .previewing:
                HStack(spacing: CicadaTheme.spacingSM) {
                    ProgressView().controlSize(.small)
                    Text(stage == .previewing ? "Counting tabs…" : "Reading Safari's tab list…")
                        .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                }
            case .ready, .importing:
                if let preview {
                    ForEach(preview.devices) { device in
                        Toggle(isOn: Binding(get: { selected.contains(device.name) },
                                             set: { on in if on { selected.insert(device.name) } else { selected.remove(device.name) } })) {
                            Text(SafariTabsDevice.line(device)).font(CicadaTheme.bodyFont)
                        }
                        .toggleStyle(.checkbox)
                        .disabled(stage == .importing || device.count == 0)
                        .accessibilityLabel(SafariTabsDevice.line(device))
                    }
                    // Keyed by position, not text: two identical warning strings
                    // would share an id under `\.self` and SwiftUI would render one
                    // (Task 3 review round 1, L3).
                    ForEach(Array(preview.warnings.enumerated()), id: \.offset) { _, warning in
                        Text(warning).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    HStack(spacing: CicadaTheme.spacingSM) {
                        Button(stage == .importing ? "Importing…" : "Import \(selectedCount) \(selectedCount == 1 ? "tab" : "tabs")") { importSelected() }
                            .buttonStyle(.borderedProminent)
                            .disabled(stage == .importing || selectedCount == 0)
                            .accessibilityLabel("Import \(selectedCount) tabs")
                        if stage == .importing { ProgressView().controlSize(.small) }
                    }
                }
            case .done(let summary):
                Text(summary).font(CicadaTheme.font(size: 13, weight: .semibold)).foregroundStyle(CicadaTheme.success)
                Text("Processed on the next Sleep cycle.").font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                Button("Import again") { load() }.buttonStyle(.bordered)
            case .fileError(let error):
                FullDiskAccessHint(error: error)
                Button("Try again") { load() }.buttonStyle(.bordered)
            case .failed(let message):
                Text(message).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.danger)
                    .fixedSize(horizontal: false, vertical: true)
                Button("Try again") { load() }.buttonStyle(.bordered)
            }
        }
        .onAppear { if stage == .idle { load() } }
        .onDisappear { task?.cancel() }
    }

    private var selectedCount: Int {
        (preview?.devices ?? []).filter { selected.contains($0.name) }.reduce(0) { $0 + $1.count }
    }

    private func load() {
        task?.cancel()
        stage = .reading
        task = Task { @MainActor in
            do {
                let db = try await BrowserFileReader.read(.safariTabsDb)
                let wal = try await BrowserFileReader.readIfPresent(.safariTabsWal)
                guard !Task.isCancelled else { return }
                stage = .previewing
                let p = try await APIClient.shared.previewSafariTabs(db: db, wal: wal)
                guard !Task.isCancelled else { return }
                bytes = (db, wal)
                preview = p
                selected = Set(p.devices.filter { $0.count > 0 }.map(\.name))
                stage = .ready
            } catch let e as BrowserFileError {
                stage = .fileError(e)
            } catch {
                guard !Task.isCancelled else { return }
                stage = .failed(AddSourceSheet.friendlyError(error))
            }
        }
    }

    /// Guards against a double-tap firing two imports: once `stage` has
    /// left `.ready`, a repeat activation is a no-op rather than a second
    /// POST of the same bytes.
    private func importSelected() {
        guard let bytes, stage == .ready else { return }
        stage = .importing
        let devices = Array(selected).sorted()
        task = Task { @MainActor in
            let m = SyncSafariTabs(db: bytes.db, wal: bytes.wal, devices: devices)
            let ok = await store.perform(m)
            guard !Task.isCancelled else { return }
            if ok, let r = m.result { stage = .done(BrowserImportSummary.tabs(r)) }
            else { stage = .failed(store.toast ?? "Import failed") }
        }
    }
}

/// Folder tree with checkboxes for one browser's bookmarks (R5). Default:
/// everything ticked; the user can narrow to one folder.
struct BookmarkFolderPanel: View {
    enum Browser { case safari, chrome }
    let browser: Browser

    @Environment(Store.self) private var store
    @State private var stage: BrowserImportStage = .idle
    @State private var tree: BookmarkFolderNode?
    @State private var selection = BookmarkFolderSelection.all
    @State private var data: Data?
    @State private var task: Task<Void, Never>?

    private var file: BrowserFile { browser == .safari ? .safariBookmarks : .chromeBookmarks }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            Text(browser == .safari
                 ? "Tick the folders to import — Favorites, Bookmarks Menu and Reading List are all here. Only URLs Cicada hasn't seen become new items."
                 : "Tick the folders to import from Chrome's default profile. Only URLs Cicada hasn't seen become new items.")
                .font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            switch stage {
            case .idle, .reading, .previewing:
                HStack(spacing: CicadaTheme.spacingSM) {
                    ProgressView().controlSize(.small)
                    Text("Reading bookmarks…").font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                }
            case .ready, .importing:
                if let tree {
                    ScrollView {
                        VStack(alignment: .leading, spacing: 2) {
                            BookmarkFolderRow(node: tree, depth: 0, selection: $selection, disabled: stage == .importing)
                        }
                    }
                    .frame(maxHeight: 220)
                    let count = selection.selectedCount(in: tree)
                    HStack(spacing: CicadaTheme.spacingSM) {
                        Button(stage == .importing ? "Importing…" : "Import \(count) \(count == 1 ? "bookmark" : "bookmarks")") { importSelected() }
                            .buttonStyle(.borderedProminent)
                            .disabled(stage == .importing || count == 0)
                            .accessibilityLabel("Import \(count) bookmarks")
                        if stage == .importing { ProgressView().controlSize(.small) }
                    }
                }
            case .done(let summary):
                Text(summary).font(CicadaTheme.font(size: 13, weight: .semibold)).foregroundStyle(CicadaTheme.success)
                Text("Processed on the next Sleep cycle.").font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                Button("Import again") { load() }.buttonStyle(.bordered)
            case .fileError(let error):
                FullDiskAccessHint(error: error)
                Button("Try again") { load() }.buttonStyle(.bordered)
            case .failed(let message):
                Text(message).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.danger)
                    .fixedSize(horizontal: false, vertical: true)
                Button("Try again") { load() }.buttonStyle(.bordered)
            }
        }
        .onAppear { if stage == .idle { load() } }
        .onDisappear { task?.cancel() }
    }

    private func load() {
        task?.cancel()
        stage = .reading
        task = Task { @MainActor in
            do {
                let bytes = try await BrowserFileReader.read(file)
                guard !Task.isCancelled else { return }
                stage = .previewing
                let p = try await APIClient.shared.previewBookmarks(
                    chromeData: browser == .chrome ? bytes : nil, safariData: browser == .safari ? bytes : nil)
                guard !Task.isCancelled else { return }
                data = bytes
                tree = p.sources.first?.tree
                selection = .all
                stage = tree == nil ? .failed("No bookmarks found in that file.") : .ready
            } catch let e as BrowserFileError {
                stage = .fileError(e)
            } catch {
                guard !Task.isCancelled else { return }
                stage = .failed(AddSourceSheet.friendlyError(error))
            }
        }
    }

    /// Same double-tap guard as `SafariTabsPanel.importSelected`.
    private func importSelected() {
        guard let data, stage == .ready else { return }
        stage = .importing
        let folders = selection.requestFolders
        task = Task { @MainActor in
            let m = SyncBrowserBookmarks(chromeData: browser == .chrome ? data : nil, safariData: browser == .safari ? data : nil, folders: folders)
            let ok = await store.perform(m)
            guard !Task.isCancelled else { return }
            if ok, let r = m.result { stage = .done(BrowserImportSummary.bookmarks(r)) }
            else { stage = .failed(store.toast ?? "Import failed") }
        }
    }
}

/// One folder row plus its children, recursively. A `View` rather than a
/// `@ViewBuilder` function because an opaque-return function cannot call
/// itself — the concrete type here can.
private struct BookmarkFolderRow: View {
    let node: BookmarkFolderNode
    let depth: Int
    @Binding var selection: BookmarkFolderSelection
    let disabled: Bool

    var body: some View {
        Toggle(isOn: Binding(get: { selection.isSelected(node.path) }, set: { _ in selection.toggle(node) })) {
            HStack {
                Text(node.name).font(CicadaTheme.bodyFont)
                Spacer()
                Text("\(node.count)").font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
            }
        }
        .toggleStyle(.checkbox)
        .padding(.leading, CGFloat(depth) * 16)
        .disabled(disabled)
        .accessibilityLabel("\(node.name), \(node.count) bookmarks")
        ForEach(node.children) { child in
            BookmarkFolderRow(node: child, depth: depth + 1, selection: $selection, disabled: disabled)
        }
    }
}
