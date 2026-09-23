import Foundation

/// G129 slice 1 — a bookmark saved in a browser reaches the queue in seconds,
/// without a button and without a timer.
///
/// **Why a watch and not a poll, and why not a webhook.** Chrome exposes no
/// local notification a third-party process can subscribe to; the only true
/// push is a Chrome extension, which costs an install and a permission prompt
/// and is not worth it yet. Polling re-reads and re-parses a 260 KB JSON on a
/// timer to usually learn nothing, and still notices late. A file watch is both
/// the cheapest and the fastest: it costs nothing while idle and fires within a
/// second or two of the save.
///
/// **Why this lives in the app.** The launchd backend has no Full Disk Access
/// and must never read `~/Library` — the ruling behind the app-reads-bytes seam
/// in `BrowserFiles.swift`. So the watch is app-side, and detection runs only
/// while the app runs. `catchUp` is the honest other half: on launch, sync any
/// file whose signature moved since the last successful sync, which is also
/// what finally reads a browser that has never been synced at all — once the
/// person has turned it on (Track I T1: before that gate, the first launch of
/// a fresh install read Chrome with nobody asked).
///
/// Bookmarks only, deliberately. Safari's iCloud tabs live behind the same
/// seam and would be trivial to add here, but a tab opening is not a save —
/// watching them would turn "what I'm reading right now" into a constant
/// stream of captures. A bookmark is an intentional act, which is what makes
/// it worth memory.

// MARK: - Pure policy (everything decidable without a filesystem or a clock)

/// What makes a browser file worth re-reading. Size plus modification time,
/// not a content hash: the file is hundreds of KB, the watch fires on every
/// write, and hashing to discover "nothing changed" costs more than the sync
/// it saves. A false positive costs one parse that finds no new URLs; a false
/// negative cannot happen, because Chrome cannot rewrite the file without
/// moving its mtime.
struct BrowserFileSignature: Equatable, Codable, Sendable {
    let size: Int64
    let modified: Double

    init(size: Int64, modified: Double) {
        self.size = size
        self.modified = modified
    }

    /// `nil` when the file does not exist or its attributes cannot be read —
    /// the two cases that mean "there is nothing to sync", not "sync failed".
    init?(path: String) {
        guard let attrs = try? FileManager.default.attributesOfItem(atPath: path),
              let size = (attrs[.size] as? NSNumber)?.int64Value,
              let modified = attrs[.modificationDate] as? Date
        else { return nil }
        self.size = size
        self.modified = modified.timeIntervalSince1970
    }
}

/// What the status light says. One value per browser row, resolved from the
/// app's own watch plus the backend's `sync_state.json` record for that
/// channel — neither half knows the whole story on its own.
enum BrowserWatchState: String, Sendable, CaseIterable {
    /// Browser or profile not installed. Not a problem, just nothing here.
    case absent
    /// The file exists but could not be read — the one state with a fix
    /// (Full Disk Access), which is why it is distinct from `failed`.
    case blocked
    /// Watching, and everything the browser has is already in memory.
    case watching
    /// A sync is running right now.
    case syncing
    /// The file moved and we have not caught up — the watch is not armed, or
    /// the app was closed when it changed.
    case stale
    /// The last sync attempt failed for a reason that is not permission.
    case failed
    /// Present, but the person has not turned it on (Track I T1, design §4.3).
    /// Nothing is read until they do — that is the point, not a fault.
    case off

    /// Whether this state should read as healthy in the UI. `absent` is not
    /// unhealthy — a browser you do not use is not a fault to report — and
    /// neither is `off`: a browser nobody asked Cicada to read is not behind.
    var isHealthy: Bool { self == .watching || self == .syncing || self == .absent || self == .off }
}

enum BrowserWatchPolicy {
    /// The channels this watcher covers, in display order, each with the file
    /// whose changes mean "the user saved something". Generalised over
    /// `BrowserFile` rather than special-cased per browser, so G119's Arc,
    /// Brave and Firefox rows join by adding a case there and a pair here.
    static let watched: [(channel: String, file: BrowserFile)] = [
        ("chrome-bookmarks", .chromeBookmarks),
        ("safari-bookmarks", .safariBookmarks),
    ]

    static func file(for channel: String) -> BrowserFile? {
        watched.first { $0.channel == channel }?.file
    }

    /// Is this change worth a sync?
    ///
    /// `current == nil` means the file is gone — nothing to read, and never an
    /// error. `lastSynced == nil` means this browser has never been synced, so
    /// the answer is yes even if the file is old: that is the case that finally
    /// reads a browser the product has listed and never opened — **once the
    /// person turned it on** (Track I T1; `shouldSync(current:lastSynced:enabled:)`
    /// is what every sync decision uses; this two-argument form is only the
    /// light's "up to date" question).
    static func shouldSync(current: BrowserFileSignature?, lastSynced: BrowserFileSignature?) -> Bool {
        guard let current else { return false }
        guard let lastSynced else { return true }
        return current != lastSynced
    }

    /// Track I T1 (design §4.3, F1): the per-channel consent flag. Machine-global,
    /// like the signature key beside it (`cicada.browserWatch.<channel>`), because
    /// the browser file it guards is machine-global too.
    static func enabledKey(_ channel: String) -> String { "cicada.browserWatch.enabled.\(channel)" }

    /// `flag` is what a person set; `nil` means nobody ever did. A stored
    /// signature means this install synced the browser before consent was a gate
    /// (G129 slice 1), so it counts as on — an existing user loses nothing. An
    /// explicit `false` outranks it (R-IA2).
    static func isEnabled(flag: Bool?, hasSignature: Bool) -> Bool { flag ?? hasSignature }

    /// F1: catch-up used to read any never-synced browser at first launch — before
    /// the first-run gate had decided anything, and able to make `graphIsEmpty`
    /// false under it (F1b). Consent comes first now; the signature rule is unchanged.
    static func shouldSync(current: BrowserFileSignature?, lastSynced: BrowserFileSignature?, enabled: Bool) -> Bool {
        enabled && shouldSync(current: current, lastSynced: lastSynced)
    }

    /// The status light. Order matters: a permission problem outranks
    /// staleness, because it is the reason for the staleness and the only one
    /// with something for the user to do. A present browser nobody turned on
    /// reads `.off` before any staleness question (R-IA3): "Behind" would say
    /// Cicada failed to catch up on something nobody asked it to read.
    static func state(
        fileExists: Bool,
        enabled: Bool,
        blocked: Bool,
        syncing: Bool,
        armed: Bool,
        upToDate: Bool,
        lastSyncFailed: Bool
    ) -> BrowserWatchState {
        if syncing { return .syncing }
        if blocked { return .blocked }
        if !fileExists { return .absent }
        if !enabled { return .off }
        if lastSyncFailed { return .failed }
        if armed && upToDate { return .watching }
        return .stale
    }

    /// How long to wait for the writes to settle before syncing.
    ///
    /// Chrome does not write its bookmark file once; it replaces it, and a
    /// directory watch sees the temp file appear, the rename, and often an
    /// attribute change besides. Syncing on the first of those would read a
    /// half-written file and then sync twice more for the same bookmark.
    static let debounce: Duration = .milliseconds(1_200)

    /// A floor on how often one channel may sync, so a browser that rewrites
    /// its file in a loop cannot turn into a request loop.
    static let minimumInterval: Duration = .seconds(5)
}

// MARK: - The watch itself

/// Arms one directory watch per browser and syncs when the file underneath it
/// moves.
///
/// **The trap this is shaped around:** Chrome replaces `Bookmarks` atomically —
/// it writes a temp file and renames it over the old one. A `DispatchSource`
/// opened on the *file* holds a descriptor to the old inode, which after the
/// first save is an unlinked file nobody will ever write again: the watch fires
/// once and then goes quiet forever, which looks exactly like a feature that
/// works in testing and not in life. Watching the containing *directory*
/// survives the replace, because the directory is the thing that persists.
@MainActor
@Observable
final class BrowserWatcher {
    private(set) var states: [String: BrowserWatchState] = [:]
    /// The permission failure, when there is one, so the row can show the fix.
    private(set) var errors: [String: BrowserFileError] = [:]

    private var sources: [String: DispatchSourceFileSystemObject] = [:]
    private var pending: [String: Task<Void, Never>] = [:]
    private var lastSyncStarted: [String: ContinuousClock.Instant] = [:]
    private var syncing: Set<String> = []

    /// Strong, deliberately. A `weak` reference here made every sync a silent
    /// no-op the moment nothing else held the store — no error, no state
    /// change, just a watch that fired and did nothing, which is the exact
    /// failure this feature exists to remove. There is no cycle to avoid: the
    /// app owns both, and `Store` knows nothing about the watcher.
    private var store: Store?
    private let defaults: UserDefaults
    private let channels: [(channel: String, file: BrowserFile)]
    private let paths: (BrowserFile) -> [URL]
    private let debounce: Duration
    private let minimumInterval: Duration
    /// Injected so tests drive the watcher without touching a real browser.
    private let performSync: @MainActor (String, Store) async throws -> String

    /// Everything a real browser supplies — the channel list, where its files
    /// live, the timings — is injectable, because the behaviour worth testing
    /// is what happens when a file is replaced underneath the watch, and that
    /// cannot be provoked through a real Chrome.
    init(
        defaults: UserDefaults = .standard,
        channels: [(channel: String, file: BrowserFile)] = BrowserWatchPolicy.watched,
        paths: @escaping (BrowserFile) -> [URL] = { $0.candidatePaths },
        debounce: Duration = BrowserWatchPolicy.debounce,
        minimumInterval: Duration = BrowserWatchPolicy.minimumInterval,
        performSync: @escaping @MainActor (String, Store) async throws -> String = {
            try await BrowserImportActions.syncChannel($0, store: $1)
        }
    ) {
        self.defaults = defaults
        self.channels = channels
        self.paths = paths
        self.debounce = debounce
        self.minimumInterval = minimumInterval
        self.performSync = performSync
    }

    // No `deinit` cancelling the sources: they are main-actor state and a
    // `deinit` is not isolated. `stop()` is the teardown, and this object lives
    // for the life of the app, so the descriptors it holds are released when
    // the process is.

    // MARK: Lifecycle

    /// Arm every watch and catch up on anything that changed while the app was
    /// closed. Safe to call more than once; a channel already armed is left be.
    func start(store: Store) {
        self.store = store
        for (channel, file) in channels {
            arm(channel: channel, file: file)
            refreshState(channel: channel, file: file)
        }
        Task { await catchUp() }
    }

    func stop() {
        for source in sources.values { source.cancel() }
        sources.removeAll()
        for task in pending.values { task.cancel() }
        pending.removeAll()
    }

    /// Sync every turned-on channel whose file moved since its last successful
    /// sync. This is what covers the app being closed when the bookmark was
    /// saved. A channel nobody turned on is skipped (Track I T1, F1).
    func catchUp() async {
        for (channel, file) in channels {
            let current = signature(of: file)
            if BrowserWatchPolicy.shouldSync(current: current, lastSynced: lastSynced(channel),
                                             enabled: isEnabled(channel)) {
                await sync(channel: channel, file: file)
            }
        }
    }

    // MARK: State

    func state(for channel: String) -> BrowserWatchState? { states[channel] ?? externalStates[channel] }
    func error(for channel: String) -> BrowserFileError? { errors[channel] ?? externalErrors[channel] }

    /// R-LS26 — a local source the app reads (a watched folder, Wispr Flow;
    /// `LocalSourceWatcher`) lights the same four views through the same two
    /// lookups above, instead of every view learning a second watcher. `nil`
    /// clears the light (a folder that is not on this Mac shows none).
    private(set) var externalStates: [String: BrowserWatchState] = [:]
    private var externalErrors: [String: BrowserFileError] = [:]

    func publish(_ state: BrowserWatchState?, error: BrowserFileError?, for channel: String) {
        externalStates[channel] = state
        externalErrors[channel] = error
    }

    /// Whether the person has turned this browser on (R-IA2). Read fresh from
    /// defaults on every call — the flag is written by the watcher itself and,
    /// in part b, by the Welcome, so a cached copy would go stale.
    func isEnabled(_ channel: String) -> Bool {
        BrowserWatchPolicy.isEnabled(
            flag: defaults.object(forKey: BrowserWatchPolicy.enabledKey(channel)) as? Bool,
            hasSignature: lastSynced(channel) != nil
        )
    }

    /// The person turned this browser on without a Sync now of their own (the
    /// `+` panel's all-folders import; part b's Welcome tick). Records consent and
    /// catches up through the watch's own path, so the signature is recorded and
    /// the light reads Watching.
    func enable(_ channel: String) {
        guard let file = channels.first(where: { $0.channel == channel })?.file else { return }
        defaults.set(true, forKey: BrowserWatchPolicy.enabledKey(channel))
        refreshState(channel: channel, file: file)
        Task { await syncIfChanged(channel: channel, file: file) }
    }

    /// A Sync now on a watched browser (R-IA2): turns it on, then syncs through the
    /// SAME path the watch uses — one sync, the signature recorded — and hands the
    /// one-line result back to the button that asked. Before this, a Sync now went
    /// around the watcher, so the watcher re-read the whole file on its next event.
    func syncNow(_ channel: String) async throws -> String {
        guard let file = channels.first(where: { $0.channel == channel })?.file else {
            throw BrowserImportActions.ImportActionError.failed("Unknown channel \(channel)")
        }
        defaults.set(true, forKey: BrowserWatchPolicy.enabledKey(channel))
        switch await sync(channel: channel, file: file) {
        case .success(let line)?: return line
        case .failure(let error)?: throw error
        case nil: return "Already syncing…"
        }
    }

    /// Whether this channel is one the app can watch at all — a row for a
    /// channel that is not watched (iCloud tabs, Notes) must not claim a light.
    /// `nonisolated` because it answers from the static policy alone and is
    /// asked from wherever a row is being built.
    nonisolated static func isWatched(_ channel: String) -> Bool {
        BrowserWatchPolicy.file(for: channel) != nil
    }

    private func refreshState(channel: String, file: BrowserFile) {
        let current = signature(of: file)
        let blocked: Bool
        if case .notReadable = errors[channel] { blocked = true } else { blocked = false }
        states[channel] = BrowserWatchPolicy.state(
            fileExists: current != nil,
            enabled: isEnabled(channel),
            blocked: blocked,
            syncing: syncing.contains(channel),
            armed: sources[channel] != nil,
            upToDate: !BrowserWatchPolicy.shouldSync(current: current, lastSynced: lastSynced(channel)),
            lastSyncFailed: failedChannels.contains(channel)
        )
    }

    private var failedChannels: Set<String> = []

    // MARK: The watch

    private func arm(channel: String, file: BrowserFile) {
        guard sources[channel] == nil else { return }
        // The directory, not the file — see the type's doc comment.
        guard let path = paths(file).first?.deletingLastPathComponent().path else { return }
        let descriptor = open(path, O_EVTONLY)
        guard descriptor >= 0 else { return }

        let source = DispatchSource.makeFileSystemObjectSource(
            fileDescriptor: descriptor,
            eventMask: [.write, .delete, .rename],
            queue: .main
        )
        source.setEventHandler { [weak self] in
            self?.fileChanged(channel: channel, file: file)
        }
        source.setCancelHandler { close(descriptor) }
        source.resume()
        sources[channel] = source
    }

    /// Coalesce the burst of events one save produces into a single sync.
    private func fileChanged(channel: String, file: BrowserFile) {
        pending[channel]?.cancel()
        pending[channel] = Task { [weak self] in
            try? await Task.sleep(for: self?.debounce ?? BrowserWatchPolicy.debounce)
            guard !Task.isCancelled, let self else { return }
            await self.syncIfChanged(channel: channel, file: file)
        }
    }

    private func syncIfChanged(channel: String, file: BrowserFile) async {
        if let started = lastSyncStarted[channel],
           ContinuousClock.now - started < minimumInterval {
            return
        }
        let current = signature(of: file)
        guard BrowserWatchPolicy.shouldSync(current: current, lastSynced: lastSynced(channel),
                                            enabled: isEnabled(channel)) else {
            refreshState(channel: channel, file: file)
            return
        }
        await sync(channel: channel, file: file)
    }

    /// Returns the outcome so `syncNow` can hand it to the button that asked;
    /// the watch's own callers ignore it. `nil` when nothing ran (no store yet,
    /// or this channel is already syncing).
    @discardableResult
    private func sync(channel: String, file: BrowserFile) async -> Result<String, Error>? {
        guard let store, !syncing.contains(channel) else { return nil }
        // Read the signature BEFORE the sync: a bookmark saved while the sync
        // is in flight must not be recorded as already synced.
        let before = signature(of: file)
        syncing.insert(channel)
        lastSyncStarted[channel] = ContinuousClock.now
        refreshState(channel: channel, file: file)

        let result: Result<String, Error>
        do {
            let line = try await performSync(channel, store)
            errors[channel] = nil
            failedChannels.remove(channel)
            if let before { record(before, for: channel) }
            result = .success(line)
        } catch let error as BrowserFileError {
            errors[channel] = error
            if case .notReadable = error {} else { failedChannels.insert(channel) }
            result = .failure(error)
        } catch {
            failedChannels.insert(channel)
            result = .failure(error)
        }
        syncing.remove(channel)
        refreshState(channel: channel, file: file)
        return result
    }

    // MARK: Signatures

    private func signature(of file: BrowserFile) -> BrowserFileSignature? {
        for url in paths(file) {
            if let signature = BrowserFileSignature(path: url.path) { return signature }
        }
        return nil
    }

    private func defaultsKey(_ channel: String) -> String { "cicada.browserWatch.\(channel)" }

    private func lastSynced(_ channel: String) -> BrowserFileSignature? {
        guard let data = defaults.data(forKey: defaultsKey(channel)) else { return nil }
        return try? JSONDecoder().decode(BrowserFileSignature.self, from: data)
    }

    private func record(_ signature: BrowserFileSignature, for channel: String) {
        guard let data = try? JSONEncoder().encode(signature) else { return }
        defaults.set(data, forKey: defaultsKey(channel))
    }
}
