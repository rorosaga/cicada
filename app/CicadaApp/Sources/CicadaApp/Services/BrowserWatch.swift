import CoreServices
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

/// Round 4 review (task 3, round 1) — is a browser file here, refused, or not here? One answer for the watch's light
/// and `LocalInventory`'s Welcome row, so the two never disagree.
///
/// **Why an open and not a stat.** Without Full Disk Access, macOS answers a stat of a protected file as "no such
/// file" (`BrowserFileReader.readIfPresent`'s L2 note), so a signature-only light turned a blocked Safari into an
/// absent one: the row had no button and said Safari had no bookmarks — on the usual fresh install. `isReadableFile`
/// is no better (it says yes to a file TCC refuses). Only an open's errno tells the three apart. Nothing is read —
/// the descriptor closes at once — so this needs no consent and prompts for nothing (Track I T1 still holds).
enum BrowserFileAccess: Equatable, Sendable {
    case present
    /// The path whose open was refused, for the Full Disk Access sentence.
    case blocked(String)
    case absent

    static func probe(_ urls: [URL]) -> BrowserFileAccess {
        var refused: String?
        for url in urls {
            let fd = open(url.path, O_RDONLY)
            if fd >= 0 {
                close(fd)
                return .present
            }
            if errno != ENOENT && errno != ENOTDIR, refused == nil { refused = url.path }
        }
        return refused.map(BrowserFileAccess.blocked) ?? .absent
    }
}

enum BrowserWatchPolicy {
    /// The channels this watcher covers, in display order, each with the file
    /// whose changes mean "the user saved something". Generalised over
    /// `BrowserFile` rather than special-cased per browser, so G119's Arc,
    /// Brave and Firefox rows join by adding a case there and a pair here.
    static let watched: [(channel: String, file: BrowserFile)] = [
        ("chrome-bookmarks", .chromeBookmarks),
        ("safari-bookmarks", .safariBookmarks),
        // Round 4 (C9): the Chromium family — read only once turned on (Track I T1), through the same watch and gate.
        ("brave-bookmarks", .braveBookmarks),
        ("vivaldi-bookmarks", .vivaldiBookmarks),
        ("comet-bookmarks", .cometBookmarks),
        ("dia-bookmarks", .diaBookmarks),
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

    /// G191 live (2026-10-14) — the browser watch's own settle time, shorter than the folder watches' `debounce`:
    /// the stream reports only events on the bookmark file's own name (`BrowserFileEvents`), so a temp file's writes
    /// never reach it, and the rename that lands the finished file is the last event of a save. 300 ms still folds
    /// the pair a swap reports (both names, one save) into one sync, and keeps the question inside its 2 s budget.
    static let bookmarkDebounce: Duration = .milliseconds(300)

    /// How long FSEvents may hold an event before it reports it (its `latency`).
    static let streamLatency: TimeInterval = 0.05

    /// G191 live — how often an armed-but-refused browser (Safari before Full Disk Access) is asked again whether it
    /// can be read now. Only while one is refused: a single `open` per tick, nothing read.
    static let accessRecheck: Duration = .seconds(5)

    /// The settle and stream latency together — what a save costs before the read starts (the budget test sums it).
    static var watchDelay: TimeInterval {
        TimeInterval(bookmarkDebounce.components.seconds)
            + TimeInterval(bookmarkDebounce.components.attoseconds) / 1e18 + streamLatency
    }

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
///
/// **G191 live (2026-10-14): an FSEvents stream, not a kqueue on the directory.** Measured on the owner's Mac: Safari
/// rewrote `Bookmarks.plist` and nothing synced. A kqueue `.write` on a directory fires only when an entry is added,
/// removed or renamed *in that directory* — not when a file in it is rewritten in place, nor when a save swaps the
/// file in from a temp file elsewhere — and its descriptor was opened once, at launch, when Safari's folder may
/// still have been refused (Full Disk Access granted later never reached it). An FSEvents stream on the folder with
/// per-file events (`BrowserFileEvents`) sees every way a file can change by its path, filtered to the bookmark
/// file's own name; and an armed browser whose file was refused is re-armed once it can be read
/// (`refreshAccess`, on the app becoming active and every `accessRecheck` while one is refused).
@MainActor
@Observable
final class BrowserWatcher {
    private(set) var states: [String: BrowserWatchState] = [:]
    /// The permission failure, when there is one, so the row can show the fix.
    private(set) var errors: [String: BrowserFileError] = [:]

    private var sources: [String: BrowserFileEvents] = [:]
    /// Whether the file could be read when its stream was armed — a stream armed while macOS refused it (Safari
    /// before Full Disk Access) is armed again once it can be (`refreshAccess`).
    private var armedReadable: [String: Bool] = [:]
    /// A change seen while that channel was syncing, or inside `minimumInterval`: synced once the way is clear
    /// (G191 live — before, it was dropped until the next save), with whether the watch saw it (`live`).
    private var owed: [String: Bool] = [:]
    private var recheck: Task<Void, Never>?
    private var pending: [String: Task<Void, Never>] = [:]
    private var lastSyncStarted: [String: ContinuousClock.Instant] = [:]
    private var syncing: Set<String> = []
    /// R-SR11 — the read-and-post in flight per channel, so × can stop it.
    private var running: [String: Task<String, Error>] = [:]

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
    private let accessRecheck: Duration
    /// Round 4 (R-SR17) — where a running sync is announced, so every `SourceRow` can say "Syncing now" with an ×.
    /// Optional: a watcher built without one (older tests) simply reports nowhere.
    private let activity: SyncActivity?
    /// Injected so tests drive the watcher without touching a real browser.
    private let performSync: @MainActor (String, Store) async throws -> String
    /// G191 live — the early look for a save that cannot sync yet (`BrowserImportActions.peek`); injected for tests.
    private let peek: @MainActor (String) async -> Void
    /// G191 v4 — the app's own diff the instant look and the baseline read feed (`BookmarkFileDiff.shared`).
    private let diff: BookmarkFileDiff
    /// G191 v4 — the channels whose instant look is reading now, and those an event came for meanwhile.
    private var looking: Set<String> = []
    private var lookAgain: Set<String> = []
    /// G191 v4 — the stage timings of each channel's last instant look (uptime seconds), for tests and the log.
    private(set) var lookTimings: [String: SaveWhyTimings.Look] = [:]
    /// Owner decision 5 (2026-10-16): what was synced is per memory, like every other reader's cursor, so a memory the
    /// person switches to catches up on the browsers' bookmarks too. Injected for tests; the app's own reads the
    /// Store's bank, and a demo memory is never caught up (capture never writes into a demo).
    private let bankOverride: (@MainActor () -> String)?
    private let isDemoOverride: (@MainActor () -> Bool)?

    /// Everything a real browser supplies — the channel list, where its files
    /// live, the timings — is injectable, because the behaviour worth testing
    /// is what happens when a file is replaced underneath the watch, and that
    /// cannot be provoked through a real Chrome.
    init(
        defaults: UserDefaults = .standard,
        channels: [(channel: String, file: BrowserFile)] = BrowserWatchPolicy.watched,
        paths: @escaping (BrowserFile) -> [URL] = { $0.candidatePaths },
        debounce: Duration = BrowserWatchPolicy.bookmarkDebounce,
        minimumInterval: Duration = BrowserWatchPolicy.minimumInterval,
        accessRecheck: Duration = BrowserWatchPolicy.accessRecheck,
        activity: SyncActivity? = nil,
        performSync: @escaping @MainActor (String, Store) async throws -> String = {
            try await BrowserImportActions.syncChannel($0, store: $1)
        },
        peek: @escaping @MainActor (String) async -> Void = { await BrowserImportActions.peek($0) },
        diff: BookmarkFileDiff? = nil,
        bank: (@MainActor () -> String)? = nil,
        isDemo: (@MainActor () -> Bool)? = nil
    ) {
        self.bankOverride = bank
        self.isDemoOverride = isDemo
        self.peek = peek
        self.diff = diff ?? .shared
        self.defaults = defaults
        self.channels = channels
        self.paths = paths
        self.debounce = debounce
        self.minimumInterval = minimumInterval
        self.accessRecheck = accessRecheck
        self.activity = activity
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
        armedReadable.removeAll()
        for task in pending.values { task.cancel() }
        pending.removeAll()
        recheck?.cancel()
        recheck = nil
    }

    /// G191 live — a turned-on browser whose stream was armed while macOS refused its file (Safari before Full Disk
    /// Access; the measured case) is armed again once an open says it can be read, and caught up — not as a live
    /// event, so the bookmarks already there are never asked about. Called when the app becomes active (the person
    /// back from System Settings) and every `accessRecheck` while one is refused. Returns the channels re-armed.
    @discardableResult
    func refreshAccess() -> [String] {
        var rearmed: [String] = []
        for (channel, file) in channels where isEnabled(channel) && armedReadable[channel] != true {
            guard rearmIfReadable(channel: channel, file: file) else { continue }
            rearmed.append(channel)
            refreshState(channel: channel, file: file)
            Task { await syncIfChanged(channel: channel, file: file) }
        }
        scheduleRecheck()
        return rearmed
    }

    /// Arm `channel` again when its stream was armed before the file could be read and it can be now (or it was
    /// never armed: its folder appeared since). True when it did.
    private func rearmIfReadable(channel: String, file: BrowserFile) -> Bool {
        guard armedReadable[channel] != true, BrowserFileAccess.probe(paths(file)) == .present else { return false }
        sources[channel]?.cancel()
        sources[channel] = nil
        arm(channel: channel, file: file)
        return true
    }

    /// While a turned-on browser is refused, look again every `accessRecheck` — the person may grant Full Disk Access
    /// and go straight back to Safari without ever bringing Cicada to the front. Stops once none is refused.
    private func scheduleRecheck() {
        let waiting = channels.contains { isEnabled($0.channel) && armedReadable[$0.channel] != true
            && BrowserFileAccess.probe(paths($0.file)) != .absent }
        guard waiting else { recheck?.cancel(); recheck = nil; return }
        guard recheck == nil else { return }
        recheck = Task { [weak self, accessRecheck] in
            try? await Task.sleep(for: accessRecheck)
            guard !Task.isCancelled, let self else { return }
            self.recheck = nil
            self.refreshAccess()
        }
    }

    /// Owner decision 5 (2026-10-16): the memory on screen changed. Its own "what was synced" is read (a memory that
    /// never had a browser's bookmarks gets them now, as the other readers' memories get theirs), and each light is
    /// re-derived for it. A demo memory reads nothing.
    func bankChanged() async {
        for (channel, file) in channels { refreshState(channel: channel, file: file) }
        guard !currentIsDemo else { return }
        await catchUp()
    }

    /// Sync every turned-on channel whose file moved since its last successful
    /// sync. This is what covers the app being closed when the bookmark was
    /// saved. A channel nobody turned on is skipped (Track I T1, F1).
    func catchUp() async {
        guard !currentIsDemo else { return }
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
    func error(for channel: String) -> BrowserFileError? {
        errors[channel] ?? externalErrors[channel] ?? refused[channel]
    }

    /// What the open probe found when no signature could be taken (`BrowserFileAccess`) — kept apart from `errors`
    /// because it is re-derived on every refresh, while a failed read's error stays until a sync succeeds.
    private var refused: [String: BrowserFileError] = [:]

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
        // Round 4 (C9): a browser installed while the app ran had no directory to watch at launch; arm it now that
        // it is turned on (`arm` leaves an already-armed channel be).
        arm(channel: channel, file: file)
        _ = rearmIfReadable(channel: channel, file: file)   // G191 live: one armed while refused, or before consent
        scheduleRecheck()
        primeBaseline(channel: channel, file: file)   // G191 v4: the next save is named at once
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
        arm(channel: channel, file: file)
        _ = rearmIfReadable(channel: channel, file: file)   // G191 live: Try again after granting Full Disk Access
        switch await sync(channel: channel, file: file) {
        case .success(let line)?: return line
        case .failure(let error)?: throw error
        case nil: return "Already syncing…"
        }
    }

    /// R-SR11 — × on a browser row: cancels the in-flight read-and-post. The watch, the consent and the last
    /// recorded signature are untouched, so the next change (or launch) reads the file again.
    func cancel(_ channel: String) { running[channel]?.cancel() }

    /// R-OB8 — an untick on the Import page: the run in flight stops (R-SR11) and the watch stops reading this
    /// browser. What came in stays; a later Turn on or Sync now records consent again and reads.
    func disable(_ channel: String) {
        cancel(channel)
        defaults.set(false, forKey: BrowserWatchPolicy.enabledKey(channel))
        guard let file = channels.first(where: { $0.channel == channel })?.file else { return }
        refreshState(channel: channel, file: file)
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
        // Task 3 review, round 1: a missing signature may be TCC's "no such file" — ask an open which it is, so a
        // blocked Safari offers its fix instead of reading as absent. Recomputed on every refresh (never sticky), so
        // granting access and pressing Try again clears it.
        // Final review, finding 4: only for a browser the person turned on. A browser nobody chose reads Off, never
        // "Needs Full Disk Access" (R-IA3) — and is not even opened; its first Turn on reads it and, if refused,
        // the hint appears once the person has chosen.
        if current == nil, isEnabled(channel), case .blocked(let path) = BrowserFileAccess.probe(paths(file)) {
            refused[channel] = .notReadable(file, path)
        } else {
            refused[channel] = nil
        }
        let blocked: Bool
        if case .notReadable = error(for: channel) { blocked = true } else { blocked = false }
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
        let urls = paths(file)
        guard let directory = urls.first?.deletingLastPathComponent(),
              FileManager.default.fileExists(atPath: directory.path) else { return }
        let names = Set(urls.map(\.lastPathComponent))
        guard let stream = BrowserFileEvents(directory: directory.path, names: names,
                                             latency: BrowserWatchPolicy.streamLatency, handler: { [weak self] in
            self?.fileChanged(channel: channel, file: file)
        }) else { return }
        sources[channel] = stream
        // Only a turned-on browser is opened (final review, finding 4); one nobody chose is re-checked on Turn on.
        armedReadable[channel] = isEnabled(channel) && BrowserFileAccess.probe(urls) == .present
        if armedReadable[channel] != true { scheduleRecheck() } else { primeBaseline(channel: channel, file: file) }
    }

    /// Coalesce the burst of events one save produces into a single sync — and, before that settle, look at once
    /// (G191 v4, `instantLook`).
    private func fileChanged(channel: String, file: BrowserFile) {
        if isEnabled(channel) { instantLook(channel: channel, file: file) }
        pending[channel]?.cancel()
        pending[channel] = Task { [weak self] in
            try? await Task.sleep(for: self?.debounce ?? BrowserWatchPolicy.debounce)
            guard !Task.isCancelled, let self else { return }
            // G191: a sync the watch itself started, seconds after the browser wrote its file — the only kind that
            // may ask "what made you save this?".
            await self.syncIfChanged(channel: channel, file: file, live: true)
        }
    }

    /// G191 v4 — the instant look (coordinator's measurement 2026-10-15: the panel showed 4.9 s after Chrome wrote its
    /// file, with the backend's look answering in 13–37 ms). The question must not wait on anything but this browser's
    /// own file: not the settle, not a sync of this channel still running or inside its `minimumInterval`, not another
    /// browser (a Safari refused Full Disk Access, its recheck, its sync), not the network. So the first event of a
    /// save reads the file and diffs it in the app at once, and one bookmark saved since the last read is offered to
    /// the question (`BookmarkSyncSignal.offer` → `SaveWhyCenter.candidate`), which shows it unconfirmed; the early
    /// look and the sync confirm it in the background, as before. Chrome lands its file by a rename, so the first
    /// event already names the whole file; a file caught mid-write parses to nothing and is ignored
    /// (`BookmarkFileDiff.record`), and the settled sync's own diff names the link instead. One read per channel at a
    /// time; an event during it reads again after. Each channel's look is its own task, so nothing on one browser can
    /// hold another's.
    private func instantLook(channel: String, file: BrowserFile) {
        guard BookmarkSyncSignal.offer != nil else { return }   // nobody asks: nothing to look for
        guard !looking.contains(channel) else { lookAgain.insert(channel); return }
        looking.insert(channel)
        let event = SaveWhyTimings.now()
        BookmarkSyncSignal.eventAt[channel] = event
        Task { @MainActor [weak self] in
            guard let self else { return }
            var look = SaveWhyTimings.Look(event: event)
            if let data = try? await BrowserFileReader.read(file, candidates: self.paths(file)) {
                look.read = SaveWhyTimings.now()
                let named = await self.diff.observe(channel: channel, data: data, live: true)
                look.diffed = SaveWhyTimings.now()
                look.named = named != nil
                if let named {
                    BookmarkSyncSignal.offer?(named)
                } else if (self.diff.removedOnLastRead[channel] ?? 0) > 0 {
                    BookmarkSyncSignal.removed?(channel)   // a bookmark removed, none new: the "Edit bookmark" bubble
                }
            }
            self.lookTimings[channel] = look
            if let read = look.read, let diffed = look.diffed {
                SaveWhyTimings.logger.info("""
                    save-why: instant look read \(SaveWhyTimings.ms(read - event)) ms, diff \
                    \(SaveWhyTimings.ms(diffed - read)) ms, \(look.named ? "one bookmark" : "nothing new", privacy: .public)
                    """)
            }
            self.looking.remove(channel)
            if self.lookAgain.remove(channel) != nil { self.instantLook(channel: channel, file: file) }
        }
    }

    /// G191 v4 — the diff's "before" for a turned-on browser, read once when its watch is armed, so the first save
    /// after launch (or after the person turns a browser on) is named from the file with no wait. Read only for a
    /// browser the person turned on (Track I T1), off the main actor, and never when a baseline exists.
    private func primeBaseline(channel: String, file: BrowserFile) {
        guard isEnabled(channel), !diff.hasBaseline(channel) else { return }
        Task { @MainActor [weak self] in
            guard let self, !self.diff.hasBaseline(channel),
                  let data = try? await BrowserFileReader.read(file, candidates: self.paths(file)) else { return }
            _ = await self.diff.observe(channel: channel, data: data, live: false)
        }
    }

    private func syncIfChanged(channel: String, file: BrowserFile, live: Bool = false) async {
        if let started = lastSyncStarted[channel],
           ContinuousClock.now - started < minimumInterval {
            // G191 live: owed, not dropped — before, a save inside the floor waited for the next save to be read.
            let wait = minimumInterval - (ContinuousClock.now - started)
            owed[channel] = (owed[channel] ?? false) || live
            if live { Task { await peek(channel) } }   // ask now; the sync follows after the floor
            pending[channel]?.cancel()
            pending[channel] = Task { [weak self] in
                try? await Task.sleep(for: wait)
                guard !Task.isCancelled, let self else { return }
                let wasLive = self.owed.removeValue(forKey: channel) ?? live
                await self.syncIfChanged(channel: channel, file: file, live: wasLive)
            }
            return
        }
        let current = signature(of: file)
        guard BrowserWatchPolicy.shouldSync(current: current, lastSynced: lastSynced(channel),
                                            enabled: isEnabled(channel)) else {
            refreshState(channel: channel, file: file)
            return
        }
        await sync(channel: channel, file: file, live: live)
    }

    /// Returns the outcome so `syncNow` can hand it to the button that asked;
    /// the watch's own callers ignore it. `nil` when nothing ran (no store yet,
    /// or this channel is already syncing).
    @discardableResult
    private func sync(channel: String, file: BrowserFile, live: Bool = false) async -> Result<String, Error>? {
        guard let store else { return nil }
        guard !currentIsDemo else { return nil }   // owner decision 5: capture never writes into a demo memory
        guard !syncing.contains(channel) else {
            // G191 live: a save during a sync is read right after it (the signature taken before this one started
            // differs), not lost until the next save.
            owed[channel] = (owed[channel] ?? false) || live
            if live { Task { await peek(channel) } }   // ask now; the sync follows after the one running
            return nil
        }
        // Read the signature BEFORE the sync: a bookmark saved while the sync
        // is in flight must not be recorded as already synced.
        let before = signature(of: file)
        // Owner decision 5: the memory this read is for — its posts name it (G183(d)) and its signature is its own.
        let bank = currentBank
        syncing.insert(channel)
        lastSyncStarted[channel] = ContinuousClock.now
        refreshState(channel: channel, file: file)

        // R-SR11 — the read-and-post runs as its own task so × (`cancel`) can stop it; awaiting it inline left
        // nothing to cancel.
        // G191: `live` rides the read-and-post as a task-local, so `syncChannel` hands it to the save-why question.
        let work = Task { @MainActor [performSync] in
            try await BankScope.bound(to: bank) {
                try await BookmarkSyncSignal.$live.withValue(live) { try await performSync(channel, store) }
            }
        }
        running[channel] = work
        activity?.began(channel, cancel: { [weak self] in self?.cancel(channel) })
        let result: Result<String, Error>
        do {
            let line = try await work.value
            errors[channel] = nil
            failedChannels.remove(channel)
            if let before { record(before, for: channel, bank: bank) }
            result = .success(line)
        } catch let error where SyncCancellation.isCancellation(error) {
            // R-SR11: stopped, not failed — no light, no error, and no signature recorded.
            result = .failure(CancellationError())
        } catch BrowserImportActions.ImportActionError.busy {
            // Final review, finding 2: an earlier sync of this bank is still saving on the backend (409). Not a
            // failure — no light, no signature recorded, so the next change or Sync now reads the file again.
            result = .failure(BrowserImportActions.ImportActionError.busy)
        } catch let error as BrowserFileError {
            errors[channel] = error
            if case .notReadable = error {} else { failedChannels.insert(channel) }
            result = .failure(error)
        } catch {
            failedChannels.insert(channel)
            result = .failure(error)
        }
        running[channel] = nil
        activity?.ended(channel)
        syncing.remove(channel)
        refreshState(channel: channel, file: file)
        if let wasLive = owed.removeValue(forKey: channel) {
            Task { [weak self] in await self?.syncIfChanged(channel: channel, file: file, live: wasLive) }
        }
        return result
    }

    // MARK: Signatures

    private func signature(of file: BrowserFile) -> BrowserFileSignature? {
        for url in paths(file) {
            if let signature = BrowserFileSignature(path: url.path) { return signature }
        }
        return nil
    }

    private var currentBank: String { bankOverride?() ?? store?.bank ?? "default" }
    private var currentIsDemo: Bool { isDemoOverride?() ?? DemoMode.isActive(store?.banks.value) }
    /// The memory `currentBank` names is the active one: the roster has loaded and `Store.bank` has caught up with it
    /// (`Store.refresh([.banks])` assigns the roster before `hydrate(bank:)` moves `Store.bank`). An injected bank is
    /// always resolved.
    private var bankResolved: Bool {
        if bankOverride != nil { return true }
        guard let store, let active = store.banks.value?.active, !active.isEmpty else { return false }
        return active == store.bank
    }

    /// What was synced, per connection (G181) and per memory (owner decision 5, 2026-10-16).
    nonisolated static func signatureKey(_ channel: String, bank: String) -> String {
        ServerConnection.current.scoped("cicada.browserWatch.\(bank).\(channel)")
    }

    /// The key before memories had their own: one per connection. Read once, by the first memory that asks, and moved.
    nonisolated static func legacySignatureKey(_ channel: String) -> String {
        ServerConnection.current.scoped("cicada.browserWatch.\(channel)")
    }

    private func lastSynced(_ channel: String) -> BrowserFileSignature? { lastSynced(channel, bank: currentBank) }

    private func lastSynced(_ channel: String, bank: String) -> BrowserFileSignature? {
        if let data = defaults.data(forKey: Self.signatureKey(channel, bank: bank)) {
            return try? JSONDecoder().decode(BrowserFileSignature.self, from: data)
        }
        // A signature from before it was per memory belongs to the memory that was synced then — the one on screen
        // at the first launch after the upgrade. Moved to it, consent kept explicit (a stored signature counted as
        // consent, R-IA2), so another memory never reads as "turned off" for lacking one.
        let legacy = Self.legacySignatureKey(channel)
        guard let data = defaults.data(forKey: legacy) else { return nil }
        // Until the Store knows which memory is active (`Store.bank` is its placeholder "default" until `hydrate()`
        // reads the roster, which runs after `start(store:)`), the old signature is only read, never moved: moving it
        // then would hand it to "default" and leave the memory that really had it to read every bookmark again.
        guard bankResolved else { return try? JSONDecoder().decode(BrowserFileSignature.self, from: data) }
        defaults.set(data, forKey: Self.signatureKey(channel, bank: bank))
        defaults.removeObject(forKey: legacy)
        if defaults.object(forKey: BrowserWatchPolicy.enabledKey(channel)) == nil {
            defaults.set(true, forKey: BrowserWatchPolicy.enabledKey(channel))
        }
        return try? JSONDecoder().decode(BrowserFileSignature.self, from: data)
    }

    private func record(_ signature: BrowserFileSignature, for channel: String, bank: String) {
        guard let data = try? JSONEncoder().encode(signature) else { return }
        defaults.set(data, forKey: Self.signatureKey(channel, bank: bank))
    }
}

// MARK: - The stream

/// G191 live — one FSEvents stream on a browser's folder, reporting only events on the bookmark file's own name(s).
/// Per-file events (`kFSEventStreamCreateFlagFileEvents`) name the path that changed whatever the save did — an
/// in-place write, a rename from a temp file beside it, a swap from a temp folder elsewhere — and the stream lives on
/// the folder's path, not a descriptor, so a replaced file never leaves it watching a dead inode. Delivered on the
/// main queue. `cancel()` is the teardown; it is also run on deinit.
final class BrowserFileEvents {
    private var stream: FSEventStreamRef?
    private let names: Set<String>
    private let handler: @MainActor () -> Void

    init?(directory: String, names: Set<String>, latency: TimeInterval, handler: @escaping @MainActor () -> Void) {
        self.names = names
        self.handler = handler
        var context = FSEventStreamContext(version: 0, info: nil, retain: nil, release: nil, copyDescription: nil)
        context.info = Unmanaged.passUnretained(self).toOpaque()
        let callback: FSEventStreamCallback = { _, info, count, paths, _, _ in
            guard let info else { return }
            let events = Unmanaged<BrowserFileEvents>.fromOpaque(info).takeUnretainedValue()
            let changed = (unsafeBitCast(paths, to: NSArray.self) as? [String]) ?? []
            guard BrowserFileEvents.matches(changed.prefix(count), names: events.names) else { return }
            MainActor.assumeIsolated { events.handler() }
        }
        let flags = FSEventStreamCreateFlags(kFSEventStreamCreateFlagUseCFTypes | kFSEventStreamCreateFlagFileEvents
                                             | kFSEventStreamCreateFlagNoDefer)
        guard let stream = FSEventStreamCreate(nil, callback, &context, [directory] as CFArray,
                                               FSEventStreamEventId(kFSEventStreamEventIdSinceNow), latency, flags)
        else { return nil }
        FSEventStreamSetDispatchQueue(stream, .main)
        guard FSEventStreamStart(stream) else {
            FSEventStreamInvalidate(stream)
            FSEventStreamRelease(stream)
            return nil
        }
        self.stream = stream
    }

    /// Whether any reported path is the watched file (by its last component: FSEvents reports the canonical path,
    /// `/private/var/…` for `/var/…`, so a full-path compare would miss).
    static func matches<S: Sequence>(_ paths: S, names: Set<String>) -> Bool where S.Element == String {
        paths.contains { names.contains(($0 as NSString).lastPathComponent) }
    }

    func cancel() {
        guard let stream else { return }
        FSEventStreamStop(stream)
        FSEventStreamInvalidate(stream)
        FSEventStreamRelease(stream)
        self.stream = nil
    }

    deinit { cancel() }
}
