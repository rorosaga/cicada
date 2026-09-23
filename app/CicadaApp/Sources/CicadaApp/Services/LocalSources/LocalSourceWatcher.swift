import Foundation

/// The backend calls a local source makes — `APIClient` in the app, a fake in
/// tests (the same injection `BrowserWatcher.performSync` uses).
protocol LocalSourcesAPI: Sendable {
    func fetchFolders() async throws -> [FolderRegistration]
    func registerFolder(label: String, path: String, projectName: String,
                        authorship: [FolderAuthorshipRule]) async throws -> FolderRegistration
    func updateFolder(id: String, authorship: [FolderAuthorshipRule]) async throws -> FolderRegistration
    func removeFolder(id: String) async throws
    func syncFolder(id: String, files: [FolderUpload], deleted: [String], preview: Bool,
                    resolve: Bool) async throws -> FolderSyncResult
    func fetchWisprSettings() async throws -> WisprFlowSettings
    func saveWisprSettings(_ settings: WisprFlowSettings) async throws -> WisprFlowSettings
    func postWisprFlow(_ json: Data) async throws -> WisprFlowSyncResult
}

enum FolderWatchError: Error, LocalizedError, Equatable {
    case permissionDenied
    case missing
    var errorDescription: String? {
        switch self {
        case .permissionDenied: LocalSourceCopy.folderPermissionFix
        case .missing: LocalSourceCopy.folderMissing
        }
    }
}

/// Plain, friendly copy for the two local sources (no jargon, no numbers baked in).
enum LocalSourceCopy {
    static let folderPermissionFix =
        "Cicada can't read this folder. Allow it under System Settings → Privacy & Security → Files and Folders, then try again."
    static let folderMissing = "This folder isn't on this Mac — it may live on another computer, or it moved."
    static let folderNotWatched =
        "Cicada couldn't start watching this folder. It will try again the next time it syncs."
}

/// A folder's watch, made by the watcher — `FSEventsWatch` in the app, a stand-in
/// in tests (review r1: a stream that failed to start must not read "Watching").
typealias FolderWatchFactory = @MainActor (_ path: String, _ onChange: @escaping @MainActor () -> Void) -> FSEventsWatch?

/// G133 / G134 — the local sources the APP reads (R-F1, R-N1): every watched
/// folder of the active memory and, when turned on, Wispr Flow.
///
/// Watches are FSEvents streams (recursive, file-level — `FSEventsWatch`),
/// debounced like `BrowserWatchPolicy` and floored per source so an app that
/// writes constantly (Wispr Flow's WAL during dictation) cannot become a
/// request loop. On launch and on every bank switch `reload()` catches up: a
/// folder posts only what moved since its manifest; Wispr Flow reads past its
/// cursors. Lights are published through `BrowserWatcher.publish` (R-LS26), so
/// the Sources cards, the channel page and Integrations read "Watching" through
/// the lookups they already make.
@MainActor
@Observable
final class LocalSourceWatcher {
    static let wisprChannel = "wispr-flow"

    private(set) var folders: [FolderRegistration] = []
    /// The folder's last failure, in words the person can act on.
    private(set) var folderErrors: [String: String] = [:]
    private(set) var wisprSettings = WisprFlowSettings()
    private(set) var wisprError: BrowserFileError?
    private(set) var syncing: Set<String> = []

    private let lights: BrowserWatcher
    private let api: any LocalSourcesAPI
    private let defaults: UserDefaults
    private let manifests: FolderManifestStore
    private let bookmarks: FolderBookmarks
    private let wisprRoot: URL
    private let debounce: Duration
    private let minimumInterval: Duration
    private let wisprDebounce: Duration
    private let wisprMinimumInterval: Duration
    private let resolveRoot: (String) -> URL?
    private var store: Store?
    private var bank = "default"
    private var streams: [String: FSEventsWatch] = [:]
    private var wisprStream: FSEventsWatch?
    private var pending: [String: Task<Void, Never>] = [:]
    private var lastStarted: [String: ContinuousClock.Instant] = [:]
    /// A change that arrived while its channel was already syncing, and whether
    /// any of those asks wanted paper details. Re-run once the sync ends (review
    /// r1: a save that lands during a slow upload must not stay stale until the
    /// next edit — the promise `tooSoon` already keeps inside the floor).
    private var dirty: [String: Bool] = [:]
    /// The bank the current `folders` were fetched for. A failed fetch after a
    /// bank switch must not keep syncing the previous bank's folders into the new
    /// one (review r1).
    private var foldersBank: String?
    private let makeWatch: FolderWatchFactory
    private let retryBase: Duration
    private var retryDelay: Duration
    private var reloadRetry: Task<Void, Never>?

    init(lights: BrowserWatcher,
         api: any LocalSourcesAPI = APIClient.shared,
         defaults: UserDefaults = .standard,
         manifests: FolderManifestStore = .standard,
         wisprRoot: URL = WisprFlowReader.standardRoot,
         debounce: Duration = BrowserWatchPolicy.debounce,
         minimumInterval: Duration = BrowserWatchPolicy.minimumInterval,
         wisprDebounce: Duration = .seconds(30),
         wisprMinimumInterval: Duration = .seconds(300),
         retryDelay: Duration = .seconds(2),
         resolveRoot: ((String) -> URL?)? = nil,
         makeWatch: FolderWatchFactory? = nil) {
        self.lights = lights
        self.api = api
        self.defaults = defaults
        self.manifests = manifests
        let bookmarks = FolderBookmarks(defaults: defaults)
        self.bookmarks = bookmarks
        self.wisprRoot = wisprRoot
        self.debounce = debounce
        self.minimumInterval = minimumInterval
        self.wisprDebounce = wisprDebounce
        self.wisprMinimumInterval = wisprMinimumInterval
        self.retryBase = retryDelay
        self.retryDelay = retryDelay
        self.resolveRoot = resolveRoot ?? { bookmarks.resolve($0) }
        self.makeWatch = makeWatch ?? { path, onChange in FSEventsWatch(path: path, handler: onChange) }
    }

    /// Wispr Flow is on this Mac — the Integrations row only offers what exists.
    var wisprInstalled: Bool { FileManager.default.fileExists(atPath: WisprFlowReader(root: wisprRoot).database.path) }

    /// Whether a registered folder can be reached from this Mac at all.
    func isOnThisMac(_ folder: FolderRegistration) -> Bool { resolveRoot(folder.id) != nil }

    // MARK: Lifecycle

    func start(store: Store) {
        self.store = store
        Task { await reload() }
    }

    /// Re-read the active memory's folders and Wispr Flow settings, re-arm every
    /// watch, and catch up on anything that changed while the app was closed.
    func reload() async {
        await reload(bank: store?.bank ?? bank)
    }

    /// `reload()` for a named bank — the seam a test switches banks through.
    func reload(bank newBank: String) async {
        bank = newBank
        do {
            folders = try await api.fetchFolders()
            foldersBank = newBank
            retryDelay = retryBase
        } catch {
            // The backend may still be starting (a spawned child takes seconds) or be
            // briefly down: ask again, backing off to a minute, instead of leaving every
            // folder unwatched until the next bank switch.
            scheduleReload()
            // Last-known-good is right for the SAME bank; after a switch it would arm
            // the old bank's folders and post them, under a fresh manifest key, into
            // the new one (review r1).
            if foldersBank != newBank {
                folders = []
                foldersBank = nil
            }
        }
        wisprSettings = (try? await api.fetchWisprSettings()) ?? wisprSettings
        arm()
        for folder in folders { await syncFolder(folder, resolve: false) }
        if wisprSettings.enabled { await syncWispr() }
    }

    private func scheduleReload() {
        reloadRetry?.cancel()
        let delay = retryDelay
        retryDelay = min(retryDelay * 2, .seconds(60))
        reloadRetry = Task { [weak self] in
            try? await Task.sleep(for: delay)
            guard !Task.isCancelled else { return }
            await self?.reload()
        }
    }

    private func arm() {
        for (id, stream) in streams where !folders.contains(where: { $0.id == id }) {
            stream.stop()
            streams[id] = nil
            // A folder that left (removed, or another bank's) takes its light with it.
            lights.publish(nil, error: nil, for: "folder:\(id)")
            folderErrors[id] = nil
        }
        for folder in folders where streams[folder.id] == nil {
            guard let root = resolveRoot(folder.id) else {
                lights.publish(nil, error: nil, for: folder.channelId)
                continue
            }
            // Held for the process: a watch needs its folder for as long as it runs.
            let scoped = root.startAccessingSecurityScopedResource()
            let id = folder.id
            if let stream = makeWatch(root.path, { [weak self] in self?.folderChanged(id) }) {
                streams[id] = stream
                lights.publish(.watching, error: nil, for: folder.channelId)
            } else {
                // No stream, no "Watching" (review r1): `stale` is the light for a watch
                // that is not armed. The next sync or reload arms it again.
                if scoped { root.stopAccessingSecurityScopedResource() }
                folderErrors[id] = LocalSourceCopy.folderNotWatched
                lights.publish(.stale, error: nil, for: folder.channelId)
            }
        }
        if wisprSettings.enabled, wisprStream == nil, FileManager.default.fileExists(atPath: wisprRoot.path) {
            wisprStream = FSEventsWatch(path: wisprRoot.path) { [weak self] in self?.wisprChanged() }
        } else if !wisprSettings.enabled {
            wisprStream?.stop()
            wisprStream = nil
            lights.publish(nil, error: nil, for: Self.wisprChannel)
        }
    }

    private func folderChanged(_ id: String) {
        pending[id]?.cancel()
        pending[id] = Task { [weak self] in
            try? await Task.sleep(for: self?.debounce ?? .seconds(1))
            guard !Task.isCancelled, let self, let folder = self.folders.first(where: { $0.id == id }) else { return }
            await self.syncFolder(folder, resolve: false)
        }
    }

    private func wisprChanged() {
        pending[Self.wisprChannel]?.cancel()
        pending[Self.wisprChannel] = Task { [weak self] in
            try? await Task.sleep(for: self?.wisprDebounce ?? .seconds(30))
            guard !Task.isCancelled, let self else { return }
            await self.syncWispr()
        }
    }

    /// Inside the floor, the change is not dropped: it is re-tried when the floor
    /// ends (a save burst must not leave a file stale until the next edit).
    private func tooSoon(_ channel: String, floor: Duration, retry: @escaping @MainActor () async -> Void) -> Bool {
        guard let started = lastStarted[channel], ContinuousClock.now - started < floor else { return false }
        let wait = floor - (ContinuousClock.now - started)
        pending[channel]?.cancel()
        pending[channel] = Task {
            try? await Task.sleep(for: wait)
            guard !Task.isCancelled else { return }
            await retry()
        }
        return true
    }

    // MARK: Folders (G133)

    func syncFolder(_ folder: FolderRegistration, resolve: Bool) async {
        let channel = folder.channelId
        guard let root = resolveRoot(folder.id) else { return }
        if syncing.contains(channel) {
            dirty[channel] = (dirty[channel] ?? false) || resolve
            return
        }
        if tooSoon(channel, floor: minimumInterval, retry: { [weak self] in await self?.syncFolder(folder, resolve: resolve) }) {
            return
        }
        syncing.insert(channel)
        lastStarted[channel] = .now
        lights.publish(.syncing, error: nil, for: channel)
        await runFolderSync(folder, root: root, resolve: resolve)
        syncing.remove(channel)
        guard let again = dirty.removeValue(forKey: channel),
              let latest = folders.first(where: { $0.id == folder.id }) else { return }
        // A "Sync now" that landed mid-sync keeps its promise to skip the floor.
        if again { lastStarted[channel] = nil }
        await syncFolder(latest, resolve: again)
    }

    /// The light a folder settles on after a good sync: "Watching" only while a
    /// stream really runs (review r1).
    private func settle(_ folder: FolderRegistration) {
        if streams[folder.id] == nil { arm() }
        if streams[folder.id] != nil {
            folderErrors[folder.id] = nil
            lights.publish(.watching, error: nil, for: folder.channelId)
        } else if resolveRoot(folder.id) != nil {
            folderErrors[folder.id] = LocalSourceCopy.folderNotWatched
            lights.publish(.stale, error: nil, for: folder.channelId)
        }
    }

    private func runFolderSync(_ folder: FolderRegistration, root: URL, resolve: Bool) async {
        let channel = folder.channelId
        let key = "\(bank)-\(folder.id)"
        let manifest = manifests.load(key)
        let rules = CompiledFolderRules(folder)
        let (walkError, read, deleted) = await Task.detached(priority: .utility)
            { () -> (FolderWalkError?, FolderReadResult, [String]) in
            let walk = FolderScanner.walk(root: root, rules: rules)
            // A root the app cannot list proves nothing about its files: read and
            // post nothing, above all no deletions (review r1).
            if let error = walk.rootError { return (error, FolderReadResult(), []) }
            let plan = FolderScanner.candidates(current: walk.files, manifest: manifest, unlisted: walk.unlisted)
            return (nil, FolderScanner.readUploads(root: root, changed: plan.changed, current: walk.files,
                                                   manifest: manifest),
                    plan.deleted)
        }.value
        if walkError == .permissionDenied || read.permissionDenied {
            folderErrors[folder.id] = LocalSourceCopy.folderPermissionFix
            lights.publish(.failed, error: nil, for: channel)
            return
        }
        if walkError == .unreachable {
            folderErrors[folder.id] = LocalSourceCopy.folderMissing
            lights.publish(.failed, error: nil, for: channel)
            return
        }
        var next = manifest
        for (rel, signature) in read.touched { next[rel] = signature }
        do {
            let batches = FolderScanner.batches(read.uploads)
            if batches.isEmpty, !deleted.isEmpty || resolve {
                _ = try await api.syncFolder(id: folder.id, files: [], deleted: deleted, preview: false, resolve: resolve)
            }
            for (i, batch) in batches.enumerated() {
                _ = try await api.syncFolder(id: folder.id, files: batch, deleted: i == 0 ? deleted : [],
                                             preview: false, resolve: resolve && i == batches.count - 1)
                for upload in batch {
                    next[upload.relpath] = FolderFileSignature(size: upload.size, modified: upload.mtime, sha256: upload.sha256)
                }
                manifests.save(next, for: key)
            }
            for rel in deleted { next.removeValue(forKey: rel) }
            manifests.save(next, for: key)
            settle(folder)
            if !read.uploads.isEmpty || !deleted.isEmpty {
                await store?.refresh([.channels, .sourcesOverview, .sources, .status, .inbox])
            }
        } catch {
            folderErrors[folder.id] = AddSourceSheet.friendlyError(error)
            lights.publish(.failed, error: nil, for: channel)
        }
    }

    /// "Sync now": skip the floor, and ask the backend for paper details (R-LS18).
    func syncNow(_ folder: FolderRegistration) async {
        lastStarted[folder.channelId] = nil
        await syncFolder(folder, resolve: true)
    }

    /// Register a folder the person picked, and remember where it is on this Mac.
    func addFolder(url: URL, label: String, projectName: String, agentGlobs: [String]) async throws -> FolderRegistration {
        let rules = agentGlobs.map { FolderAuthorshipRule(glob: $0, authorship: "agent") }
        let folder = try await api.registerFolder(label: label, path: url.path, projectName: projectName,
                                                  authorship: rules)
        bookmarks.save(url, for: folder.id)
        folders = (try? await api.fetchFolders()) ?? (folders.filter { $0.id != folder.id } + [folder])
        return folder
    }

    /// What a first sync would stage — every included file, posted with `preview`.
    func preview(_ folder: FolderRegistration, root: URL) async throws -> FolderSyncResult {
        let rules = CompiledFolderRules(folder)
        let (walkError, read) = await Task.detached(priority: .userInitiated) { () -> (FolderWalkError?, FolderReadResult) in
            let walk = FolderScanner.walk(root: root, rules: rules)
            if let error = walk.rootError { return (error, FolderReadResult()) }
            return (nil, FolderScanner.readUploads(root: root, changed: walk.files.keys.sorted(), current: walk.files,
                                                   manifest: [:]))
        }.value
        if walkError == .permissionDenied || read.permissionDenied { throw FolderWatchError.permissionDenied }
        if walkError == .unreachable { throw FolderWatchError.missing }
        var total = FolderSyncResult()
        total.preview = true
        for batch in FolderScanner.batches(read.uploads) {
            total.add(try await api.syncFolder(id: folder.id, files: batch, deleted: [], preview: true, resolve: false))
        }
        return total
    }

    /// Arm the new folder's watch and run its first real sync, details included.
    func startWatching(_ folder: FolderRegistration) async {
        arm()
        await syncFolder(folder, resolve: true)
    }

    func removeFolder(_ folder: FolderRegistration) async throws {
        try await api.removeFolder(id: folder.id)
        streams[folder.id]?.stop()
        streams[folder.id] = nil
        bookmarks.remove(folder.id)
        manifests.remove("\(bank)-\(folder.id)")
        lights.publish(nil, error: nil, for: folder.channelId)
        folders.removeAll { $0.id == folder.id }
        folderErrors[folder.id] = nil
        await store?.refresh([.channels, .sourcesOverview])
    }

    /// A changed "written by an agent" rule re-posts every file, so the backend can
    /// re-attribute them (R-LS10): the manifest is dropped, nothing else.
    func updateAgentGlobs(_ folder: FolderRegistration, globs: [String]) async throws {
        let updated = try await api.updateFolder(
            id: folder.id, authorship: globs.map { FolderAuthorshipRule(glob: $0, authorship: "agent") })
        if let i = folders.firstIndex(where: { $0.id == folder.id }) { folders[i] = updated }
        manifests.remove("\(bank)-\(folder.id)")
        lastStarted[folder.channelId] = nil
        await syncFolder(updated, resolve: false)
    }

    // MARK: Wispr Flow (G134)

    private var cursorKey: String { "cicada.wisprFlow.cursor.\(bank)" }

    private func loadCursor() -> WisprFlowCursor {
        guard let data = defaults.data(forKey: cursorKey) else { return WisprFlowCursor() }
        return (try? JSONDecoder().decode(WisprFlowCursor.self, from: data)) ?? WisprFlowCursor()
    }

    private func saveCursor(_ cursor: WisprFlowCursor) {
        if let data = try? JSONEncoder().encode(cursor) { defaults.set(data, forKey: cursorKey) }
    }

    /// Turn the source on or off, or change what it reads. A new "your name in
    /// meetings" list re-reads every meeting so past transcripts credit the
    /// person too (a one-time re-read, disclosed in G134).
    func setWispr(_ settings: WisprFlowSettings) async throws {
        let previous = wisprSettings
        wisprSettings = try await api.saveWisprSettings(settings)
        if wisprSettings.ownerSpeakerNames != previous.ownerSpeakerNames {
            var cursor = loadCursor()
            cursor.meetings = nil
            saveCursor(cursor)
        }
        arm()
        if wisprSettings.enabled {
            lastStarted[Self.wisprChannel] = nil
            await syncWispr()
        }
        await store?.refresh([.channels, .sourcesOverview])
    }

    /// "Sync now" on the Wispr Flow row: skip the floor.
    func syncWisprNow() async {
        lastStarted[Self.wisprChannel] = nil
        await syncWispr()
    }

    func syncWispr() async {
        let channel = Self.wisprChannel
        guard wisprSettings.enabled else { return }
        if syncing.contains(channel) {
            dirty[channel] = true
            return
        }
        if tooSoon(channel, floor: wisprMinimumInterval, retry: { [weak self] in await self?.syncWispr() }) { return }
        syncing.insert(channel)
        lastStarted[channel] = .now
        lights.publish(.syncing, error: nil, for: channel)
        await runWisprSync()
        syncing.remove(channel)
        // A write that landed mid-pass is read now, through the floor like any other
        // change, instead of waiting for Wispr Flow's next write (review r1).
        if dirty.removeValue(forKey: channel) != nil { await syncWispr() }
    }

    private func runWisprSync() async {
        let channel = Self.wisprChannel
        let reader = WisprFlowReader(root: wisprRoot)
        let includeDictation = wisprSettings.includeDictation
        var cursor = loadCursor()
        do {
            var posted = false
            for _ in 0..<20 {  // bounded catch-up: at most 20 batches per pass
                let since = cursor
                let pass = try await Task.detached(priority: .utility) {
                    try reader.read(since: since, includeDictation: includeDictation)
                }.value
                if pass.isEmpty { break }
                _ = try await api.postWisprFlow(pass.json)
                cursor = pass.cursor
                saveCursor(cursor)
                posted = true
                if !pass.hasMore { break }
            }
            wisprError = nil
            lights.publish(.watching, error: nil, for: channel)
            if posted { await store?.refresh([.channels, .sourcesOverview, .status]) }
        } catch let error as BrowserFileError {
            wisprError = error
            if case .notReadable = error {
                lights.publish(.blocked, error: error, for: channel)
            } else {
                lights.publish(.failed, error: error, for: channel)
            }
        } catch {
            lights.publish(.failed, error: nil, for: channel)
        }
    }
}
