import XCTest
@testable import CicadaApp

/// 2026-10-23 — Apple Notes keeps up once the person's own first read turned it on, and only while Notes is open
/// (`tell application "Notes"` would launch it). No test runs the real script: it would raise an Automation prompt.
@MainActor
final class AppleNotesWatcherTests: XCTestCase {
    private var defaults: UserDefaults!
    private let suite = "AppleNotesWatcherTests"

    override func setUp() {
        super.setUp()
        defaults = UserDefaults(suiteName: suite)
        defaults.removePersistentDomain(forName: suite)
    }

    override func tearDown() {
        defaults.removePersistentDomain(forName: suite)
        super.tearDown()
    }

    private static var result: NoteSyncResult {
        // swiftlint:disable:next force_try
        try! JSONDecoder().decode(NoteSyncResult.self, from: Data(#"{"new": 1, "skipped": 0}"#.utf8))
    }

    private struct Refused: LocalizedError { var errorDescription: String? { "Cicada isn't allowed to read Apple Notes." } }

    private func watcher(open: Bool = true, fail: Bool = false,
                         reads: @escaping () -> Void = {}) -> AppleNotesWatcher {
        AppleNotesWatcher(defaults: defaults, period: .seconds(3600), notesRunning: { open }, read: {
            reads()
            if fail { throw Refused() }
            return Self.result
        })
    }

    func testNothingIsReadBeforeThePersonsOwnFirstRead() async {
        var reads = 0
        let w = watcher { reads += 1 }
        w.start()
        await w.syncIfOpen()
        XCTAssertEqual(reads, 0)
        XCTAssertFalse(w.enabled)
        XCTAssertEqual(w.status, .off)
    }

    func testTheFirstReadTurnsKeepingUpOnAndIsRemembered() async throws {
        let w = watcher()
        _ = try await w.syncNow()
        XCTAssertTrue(w.enabled)
        XCTAssertTrue(defaults.bool(forKey: AppleNotesWatcher.enabledKey))
        guard case .synced = w.status else { return XCTFail("status \(w.status)") }
        XCTAssertTrue(watcher().enabled, "a relaunch keeps it on")
        w.disconnect()
    }

    func testARefusedFirstReadLeavesItOffAndSaysWhy() async {
        let w = watcher(fail: true)
        do {
            _ = try await w.syncNow()
            XCTFail("a refusal must be thrown")
        } catch {
            XCTAssertEqual(error.localizedDescription, "Cicada isn't allowed to read Apple Notes.")
        }
        XCTAssertFalse(w.enabled)
        XCTAssertEqual(w.status, .off)
    }

    func testOnceOnItReadsOnlyWhileNotesIsOpen() async throws {
        var reads = 0
        defaults.set(true, forKey: AppleNotesWatcher.enabledKey)
        let closed = watcher(open: false) { reads += 1 }
        await closed.syncIfOpen()
        XCTAssertEqual(reads, 0, "never launches Notes to read it")
        let open = watcher(open: true) { reads += 1 }
        await open.syncIfOpen()
        XCTAssertEqual(reads, 1)
        open.disconnect()
    }

    func testDisconnectStopsKeepingUpAndIsRemembered() async throws {
        var reads = 0
        let w = watcher { reads += 1 }
        _ = try await w.syncNow()
        w.disconnect()
        XCTAssertFalse(w.enabled)
        XCTAssertFalse(defaults.bool(forKey: AppleNotesWatcher.enabledKey))
        XCTAssertEqual(w.status, .off)
        await w.syncIfOpen()
        XCTAssertEqual(reads, 1, "no read after Disconnect")
    }

    func testAnUnattendedFailureKeepsItOnAndSaysWhy() async throws {
        var fail = false
        let w = AppleNotesWatcher(defaults: defaults, period: .seconds(3600), notesRunning: { true }, read: {
            if fail { throw Refused() }
            return Self.result
        })
        _ = try await w.syncNow()
        fail = true
        await w.syncIfOpen()
        XCTAssertTrue(w.enabled)
        XCTAssertEqual(w.status, .failed("Cicada isn't allowed to read Apple Notes."))
        w.disconnect()
    }
}
