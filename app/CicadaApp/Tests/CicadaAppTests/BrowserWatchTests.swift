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
        func state(exists: Bool = true, blocked: Bool = false, syncing: Bool = false,
                   armed: Bool = true, upToDate: Bool = true, failed: Bool = false) -> BrowserWatchState {
            BrowserWatchPolicy.state(fileExists: exists, blocked: blocked, syncing: syncing,
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
        XCTAssertEqual(watched, ["chrome-bookmarks", "safari-bookmarks"])
        XCTAssertFalse(BrowserWatcher.isWatched("safari-tabs"))
        XCTAssertFalse(BrowserWatcher.isWatched("notes"))
        XCTAssertTrue(BrowserWatcher.isWatched("chrome-bookmarks"))
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
    /// nothing changed while the app was running. This is the case the owner's
    /// own machine was in: Chrome listed, never once read.
    func testCatchUpSyncsABrowserThatWasNeverSynced() async throws {
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
}
