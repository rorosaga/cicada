import XCTest
@testable import CicadaApp

/// G129 slice 1 — the watch that makes a bookmark reach the queue without a
/// button. The policy half is pure; the watcher half is exercised against a
/// real temp directory, because the behaviour worth proving is what happens
/// when a file is *replaced* underneath the watch, which no amount of mocking
/// would tell us.
final class BrowserWatchPolicyTests: XCTestCase {
    private let a = BrowserFileSignature(size: 100, modified: 1_000)

    func testANeverSyncedBrowserSyncsEvenIfItsFileIsOld() {
        XCTAssertTrue(
            BrowserWatchPolicy.shouldSync(current: a, lastSynced: nil),
            "the case that finally reads a browser the product listed and never opened"
        )
    }

    func testAnUnchangedFileDoesNotSync() {
        XCTAssertFalse(BrowserWatchPolicy.shouldSync(current: a, lastSynced: a))
    }

    func testAChangeInEitherHalfOfTheSignatureSyncs() {
        XCTAssertTrue(BrowserWatchPolicy.shouldSync(
            current: BrowserFileSignature(size: 101, modified: 1_000), lastSynced: a))
        XCTAssertTrue(BrowserWatchPolicy.shouldSync(
            current: BrowserFileSignature(size: 100, modified: 1_001), lastSynced: a),
            "a bookmark can be added and another removed in the same edit, leaving the size alone")
    }

    func testAMissingFileIsNeverASync() {
        XCTAssertFalse(BrowserWatchPolicy.shouldSync(current: nil, lastSynced: a),
                       "an uninstalled browser is not a sync and not an error")
    }

    /// The light's precedence, stated as the questions it answers in order.
    func testStatePrecedence() {
        func state(exists: Bool = true, enabled: Bool = true, blocked: Bool = false, syncing: Bool = false,
                   armed: Bool = true, upToDate: Bool = true, failed: Bool = false) -> BrowserWatchState {
            BrowserWatchPolicy.state(fileExists: exists, enabled: enabled, blocked: blocked, syncing: syncing,
                                     armed: armed, upToDate: upToDate, lastSyncFailed: failed)
        }
        XCTAssertEqual(state(), .watching)
        XCTAssertEqual(state(blocked: true, syncing: true), .syncing, "what is happening now wins")
        XCTAssertEqual(state(blocked: true, failed: true), .blocked,
                       "a permission problem outranks a failure — it is the one with a fix")
        XCTAssertEqual(state(exists: false), .absent)
        XCTAssertEqual(state(exists: false, blocked: true), .blocked,
                       "an unreadable file may not be reported as an absent one")
        XCTAssertEqual(state(failed: true), .failed)
        XCTAssertEqual(state(upToDate: false), .stale)
        XCTAssertEqual(state(armed: false), .stale, "no watch means we cannot claim to be watching")
    }

    /// Watching iCloud tabs would turn "what I have open" into a capture
    /// stream. A bookmark is an intentional act; an open tab is not.
    func testOnlyBookmarksAreWatched() {
        let watched = BrowserWatchPolicy.watched.map(\.channel)
        XCTAssertEqual(watched, ["chrome-bookmarks", "safari-bookmarks", "brave-bookmarks", "vivaldi-bookmarks",
                                 "comet-bookmarks", "dia-bookmarks"])
        XCTAssertFalse(BrowserWatcher.isWatched("safari-tabs"))
        XCTAssertFalse(BrowserWatcher.isWatched("notes"))
        XCTAssertTrue(BrowserWatcher.isWatched("chrome-bookmarks"))
    }

    /// Track I T1 (design §4.3, F1) — first launch used to read Chrome before
    /// anyone was asked. A browser nobody turned on is never read, however old
    /// or new its file is.
    func testNothingSyncsBeforeTheChannelIsTurnedOn() {
        XCTAssertFalse(BrowserWatchPolicy.shouldSync(current: a, lastSynced: nil, enabled: false),
                       "F1: the never-synced case must not read without consent")
        XCTAssertTrue(BrowserWatchPolicy.shouldSync(current: a, lastSynced: nil, enabled: true))
        XCTAssertFalse(BrowserWatchPolicy.shouldSync(current: nil, lastSynced: nil, enabled: true),
                       "a missing file is still never a sync")
    }

    /// R-IA2 — an install that already synced a browser keeps it; an explicit
    /// off outranks that migration.
    func testAStoredSignatureCountsAsOnAndAnExplicitOffWins() {
        XCTAssertTrue(BrowserWatchPolicy.isEnabled(flag: nil, hasSignature: true))
        XCTAssertFalse(BrowserWatchPolicy.isEnabled(flag: nil, hasSignature: false))
        XCTAssertTrue(BrowserWatchPolicy.isEnabled(flag: true, hasSignature: false))
        XCTAssertFalse(BrowserWatchPolicy.isEnabled(flag: false, hasSignature: true))
        XCTAssertEqual(BrowserWatchPolicy.enabledKey("chrome-bookmarks"),
                       "cicada.browserWatch.enabled.chrome-bookmarks")
    }

    /// R-IA3 — present but not turned on reads Off, never Behind.
    func testAPresentBrowserNobodyTurnedOnReadsOff() {
        func state(exists: Bool = true, enabled: Bool, syncing: Bool = false) -> BrowserWatchState {
            BrowserWatchPolicy.state(fileExists: exists, enabled: enabled, blocked: false, syncing: syncing,
                                     armed: true, upToDate: false, lastSyncFailed: false)
        }
        XCTAssertEqual(state(enabled: false), .off)
        XCTAssertEqual(state(exists: false, enabled: false), .absent, "an absent browser is absent, on or off")
        XCTAssertEqual(state(enabled: false, syncing: true), .syncing, "what is happening now wins")
        XCTAssertEqual(state(enabled: true), .stale)
        XCTAssertTrue(BrowserWatchState.off.isHealthy, "not turned on is not a fault")
    }

    func testEveryLightStateHasItsOwnTitle() {
        let titles = BrowserWatchState.allCases.map(BrowserStatusLight.title(for:))
        XCTAssertEqual(Set(titles).count, titles.count)
    }
}

@MainActor
final class BrowserWatcherTests: XCTestCase {
    private var dir: URL!
    private var defaults: UserDefaults!
    /// Held for the test's lifetime on purpose: a watcher whose store has been
    /// deallocated is exactly the bug these tests caught.
    private var store: Store!
    private let suite = "cicada.browserwatch.tests"

    override func setUp() async throws {
        dir = URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent("cicada-watch-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defaults = UserDefaults(suiteName: suite)
        defaults.removePersistentDomain(forName: suite)
        store = Store()
    }

    override func tearDown() async throws {
        defaults.removePersistentDomain(forName: suite)
        try? FileManager.default.removeItem(at: dir)
    }

    private var bookmarks: URL { dir.appendingPathComponent("Bookmarks") }

    /// Exactly how Chrome saves: write a sibling temp file, then rename it over
    /// the target. The old inode is unlinked and never written again.
    private func atomicallyReplace(with contents: String) throws {
        let tmp = dir.appendingPathComponent("Bookmarks.tmp")
        try contents.write(to: tmp, atomically: false, encoding: .utf8)
        _ = try FileManager.default.replaceItemAt(bookmarks, withItemAt: tmp)
    }

    private func makeWatcher(_ onSync: @escaping @MainActor (String) -> Void) -> BrowserWatcher {
        BrowserWatcher(
            defaults: defaults,
            channels: [("chrome-bookmarks", .chromeBookmarks)],
            paths: { [dir] _ in [dir!.appendingPathComponent("Bookmarks")] },
            debounce: .milliseconds(60),
            minimumInterval: .milliseconds(1),
            performSync: { channel, _ in onSync(channel); return "ok" }
        )
    }

    private func turnOn() { defaults.set(true, forKey: BrowserWatchPolicy.enabledKey("chrome-bookmarks")) }

    /// Waits for a condition rather than sleeping a fixed time, so the test is
    /// neither flaky nor slower than it has to be.
    private func eventually(
        _ description: String, timeout: Duration = .seconds(5), _ condition: @MainActor () -> Bool
    ) async throws {
        let deadline = ContinuousClock.now + timeout
        while ContinuousClock.now < deadline {
            if condition() { return }
            try await Task.sleep(for: .milliseconds(25))
        }
        XCTFail("timed out waiting for: \(description)")
    }

    /// The regression that matters. A watch opened on the *file* dies with the
    /// first atomic replace — it fires once and then never again, which reads
    /// as "works in testing, broken in life". This asserts the second and third
    /// saves are still seen.
    func testTheWatchSurvivesRepeatedAtomicReplaces() async throws {
        turnOn()
        try atomicallyReplace(with: "{\"one\": 1}")
        var synced: [String] = []
        let watcher = makeWatcher { synced.append($0) }
        watcher.start(store: store)
        try await eventually("the initial catch-up sync") { !synced.isEmpty }

        for i in 2...3 {
            let before = synced.count
            // A distinct size each time, so a signature check cannot skip it.
            try atomicallyReplace(with: String(repeating: "x", count: i * 10))
            try await eventually("sync \(i) after an atomic replace") { synced.count > before }
        }

        XCTAssertGreaterThanOrEqual(synced.count, 3, "each replace must be noticed, not just the first")
        XCTAssertTrue(synced.allSatisfy { $0 == "chrome-bookmarks" })
        watcher.stop()
    }

    /// A browser that has never been synced is read on launch, even though
    /// nothing changed while the app was running — once it is turned on
    /// (Track I T1). This is the case the owner's own machine was in: Chrome
    /// listed, never once read.
    func testCatchUpSyncsATurnedOnBrowserThatWasNeverSynced() async throws {
        turnOn()
        try atomicallyReplace(with: "{}")
        var synced: [String] = []
        let watcher = makeWatcher { synced.append($0) }
        watcher.start(store: store)
        try await eventually("the catch-up sync") { !synced.isEmpty }
        XCTAssertEqual(synced, ["chrome-bookmarks"])
        watcher.stop()
    }

    /// The signature is only recorded after a sync succeeds, so a relaunch does
    /// not re-read a file nothing has touched — and the light says `watching`.
    func testASecondLaunchDoesNotResyncAnUnchangedFile() async throws {
        turnOn()
        try atomicallyReplace(with: "{}")
        var first: [String] = []
        let watcher = makeWatcher { first.append($0) }
        watcher.start(store: store)
        try await eventually("the first launch's sync") { !first.isEmpty }
        try await eventually("the light to settle") { watcher.state(for: "chrome-bookmarks") == .watching }
        watcher.stop()

        var second: [String] = []
        let relaunched = makeWatcher { second.append($0) }
        relaunched.start(store: store)
        try await Task.sleep(for: .milliseconds(400))
        XCTAssertTrue(second.isEmpty, "an unchanged file must not be re-read on every launch")
        XCTAssertEqual(relaunched.state(for: "chrome-bookmarks"), .watching)
        relaunched.stop()
    }

    /// A browser that is not installed is reported as absent, not as broken,
    /// and never syncs.
    func testAnAbsentBrowserIsNotAnError() async throws {
        var synced: [String] = []
        let watcher = makeWatcher { synced.append($0) }
        watcher.start(store: store)
        try await Task.sleep(for: .milliseconds(300))
        XCTAssertEqual(watcher.state(for: "chrome-bookmarks"), .absent)
        XCTAssertTrue(synced.isEmpty)
        XCTAssertTrue(BrowserWatchState.absent.isHealthy, "a browser you don't use is not a fault")
        watcher.stop()
    }

    /// F1, end to end: the file exists, nobody turned the browser on, the app
    /// launches and the file changes — nothing is read, and the light says Off.
    func testFirstLaunchReadsNoBrowserBeforeConsent() async throws {
        try atomicallyReplace(with: "{}")
        var synced: [String] = []
        let watcher = makeWatcher { synced.append($0) }
        watcher.start(store: store)
        try await Task.sleep(for: .milliseconds(300))
        XCTAssertTrue(synced.isEmpty, "catch-up read a browser nobody turned on")
        XCTAssertEqual(watcher.state(for: "chrome-bookmarks"), .off)

        try atomicallyReplace(with: String(repeating: "x", count: 40))
        try await Task.sleep(for: .milliseconds(400))
        XCTAssertTrue(synced.isEmpty, "the file-change path is gated too")
        watcher.stop()
    }

    /// A Sync now is the consent: it turns the browser on, syncs ONCE through
    /// the watcher (so the signature is recorded), and the watch is live after.
    func testSyncNowTurnsTheBrowserOnSyncsOnceAndKeepsWatching() async throws {
        try atomicallyReplace(with: "{}")
        var synced: [String] = []
        let watcher = makeWatcher { synced.append($0) }
        watcher.start(store: store)
        let line = try await watcher.syncNow("chrome-bookmarks")
        XCTAssertEqual(line, "ok")
        XCTAssertEqual(synced, ["chrome-bookmarks"])
        XCTAssertEqual(defaults.object(forKey: BrowserWatchPolicy.enabledKey("chrome-bookmarks")) as? Bool, true)
        try await eventually("the light to settle") { watcher.state(for: "chrome-bookmarks") == .watching }

        try atomicallyReplace(with: String(repeating: "y", count: 50))
        try await eventually("the watch to pick up the next save") { synced.count == 2 }
        watcher.stop()
    }

    /// R-IA2's migration: an install that synced before the gate existed has a
    /// signature and no flag, and keeps syncing.
    func testAnInstallThatSyncedBeforeTheGateKeepsWatching() async throws {
        try atomicallyReplace(with: "{}")
        turnOn()
        var first: [String] = []
        let watcher = makeWatcher { first.append($0) }
        watcher.start(store: store)
        try await eventually("the first sync") { !first.isEmpty }
        watcher.stop()
        defaults.removeObject(forKey: BrowserWatchPolicy.enabledKey("chrome-bookmarks"))

        var second: [String] = []
        let relaunched = makeWatcher { second.append($0) }
        relaunched.start(store: store)
        try atomicallyReplace(with: String(repeating: "z", count: 60))
        try await eventually("a signature alone keeps the watch on") { !second.isEmpty }
        relaunched.stop()
    }

    /// The `+` panel's all-folders import calls `enable`, which catches up.
    func testEnableCatchesUp() async throws {
        try atomicallyReplace(with: "{}")
        var synced: [String] = []
        let watcher = makeWatcher { synced.append($0) }
        watcher.start(store: store)
        try await Task.sleep(for: .milliseconds(150))
        XCTAssertTrue(synced.isEmpty)
        watcher.enable("chrome-bookmarks")
        try await eventually("enable's catch-up") { synced == ["chrome-bookmarks"] }
        watcher.stop()
    }

    /// R-SR11 — × stops the run: no failure light, no error, and no signature, so the next save reads it again.
    func testCancelStopsTheRunWithoutAFailureAndWithoutRecordingTheFile() async throws {
        try atomicallyReplace(with: "{}")
        let activity = SyncActivity()
        let watcher = BrowserWatcher(
            defaults: defaults, channels: [("chrome-bookmarks", .chromeBookmarks)],
            paths: { [dir] _ in [dir!.appendingPathComponent("Bookmarks")] },
            debounce: .milliseconds(60), minimumInterval: .milliseconds(1), activity: activity,
            performSync: { _, _ in try await Task.sleep(for: .seconds(30)); return "never" })
        watcher.start(store: store)
        let running = Task { try await watcher.syncNow("chrome-bookmarks") }
        try await eventually("the run to register") { activity.run(for: "chrome-bookmarks")?.cancellable == true }
        activity.cancel("chrome-bookmarks")
        do { _ = try await running.value; XCTFail("a cancelled sync must not report a line") }
        catch { XCTAssertTrue(SyncCancellation.isCancellation(error), "\(error)") }
        XCTAssertNil(activity.run(for: "chrome-bookmarks"))
        XCTAssertNotEqual(watcher.state(for: "chrome-bookmarks"), .failed)
        XCTAssertNil(watcher.error(for: "chrome-bookmarks"))
        XCTAssertNil(defaults.data(forKey: "cicada.browserWatch.chrome-bookmarks"), "no signature: the next change re-reads")
        watcher.stop()
    }
}
