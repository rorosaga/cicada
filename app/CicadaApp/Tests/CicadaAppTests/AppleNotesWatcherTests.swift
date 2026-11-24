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
        defaults = TestDefaults.suite(suite)
        defaults.removePersistentDomain(forName: TestDefaults.path(suite))
    }

    override func tearDown() {
        defaults.removePersistentDomain(forName: TestDefaults.path(suite))
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

    /// A read that suspends; the test resumes it when it chooses.
    private final class Gate {
        var waiting: CheckedContinuation<Void, Never>?
        var reads = 0
    }

    private func gated(_ gate: Gate) -> AppleNotesWatcher {
        AppleNotesWatcher(defaults: defaults, period: .seconds(3600), notesRunning: { true }, read: {
            gate.reads += 1
            await withCheckedContinuation { gate.waiting = $0 }
            return Self.result
        })
    }

    private func untilWaiting(_ gate: Gate) async {
        for _ in 0..<1000 where gate.waiting == nil { await Task.yield() }
    }

    /// Review of #448 — the launch or bank-switch read is unattended: a Disconnect pressed while it reads wins. Before,
    /// the late answer turned Notes back on, saved that and armed a new two-hour timer.
    func testADisconnectDuringAnUnattendedReadStaysOff() async throws {
        defaults.set(true, forKey: AppleNotesWatcher.enabledKey)
        let gate = Gate()
        let w = gated(gate)
        let read = Task { await w.syncIfOpen() }
        await untilWaiting(gate)
        XCTAssertNotNil(gate.waiting, "the read is suspended")
        w.disconnect()
        gate.waiting?.resume()
        await read.value
        XCTAssertFalse(w.enabled)
        XCTAssertFalse(defaults.bool(forKey: AppleNotesWatcher.enabledKey))
        XCTAssertFalse(w.isArmed, "no new timer")
        XCTAssertEqual(w.status, .off)
    }

    /// The person's own Refresh, then Disconnect while it reads: off, unarmed — the Refresh does not turn it back on.
    func testADisconnectDuringThePersonsOwnReadStaysOff() async throws {
        defaults.set(true, forKey: AppleNotesWatcher.enabledKey)
        let gate = Gate()
        let w = gated(gate)
        let read = Task { try await w.syncNow() }
        await untilWaiting(gate)
        w.disconnect()
        gate.waiting?.resume()
        _ = try await read.value
        XCTAssertFalse(w.enabled)
        XCTAssertFalse(defaults.bool(forKey: AppleNotesWatcher.enabledKey))
        XCTAssertFalse(w.isArmed)
        XCTAssertEqual(w.status, .off)
    }

    /// An unattended read never turns Notes on, even if the flag was off when it began (it cannot begin then).
    func testAnUnattendedReadNeverTurnsNotesOn() async {
        var reads = 0
        let w = watcher { reads += 1 }
        await w.syncIfOpen()
        await w.bankChanged()
        XCTAssertEqual(reads, 0)
        XCTAssertFalse(w.enabled)
        XCTAssertFalse(w.isArmed)
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

    // MARK: G245 (track C1) — Notes opened or brought to the front

    private final class Clock { var at = Date(timeIntervalSince1970: 1_800_000_000) }

    private func watcher(clock: Clock, open: Bool = true, floor: TimeInterval = 900,
                         reads: @escaping () -> Void) -> AppleNotesWatcher {
        AppleNotesWatcher(defaults: defaults, period: .seconds(3600), now: { clock.at },
                          center: NotificationCenter(), floor: floor, settle: .zero,
                          notesRunning: { open }, read: {
            reads()
            return Self.result
        })
    }

    func testNotesComingToTheFrontReadsOnceAndSwitchingBackAndForthDoesNot() async throws {
        var reads = 0
        let clock = Clock()
        let w = watcher(clock: clock) { reads += 1 }
        _ = try await w.syncNow()
        XCTAssertEqual(reads, 1)
        clock.at.addTimeInterval(120)
        await w.workspaceEvent(bundleId: AppleNotesWatcher.notesBundleId)
        XCTAssertEqual(reads, 1, "inside the floor of the person's own read")
        clock.at.addTimeInterval(900)
        await w.workspaceEvent(bundleId: AppleNotesWatcher.notesBundleId)
        XCTAssertEqual(reads, 2, "past the floor")
        for _ in 0..<5 {
            clock.at.addTimeInterval(60)
            await w.workspaceEvent(bundleId: AppleNotesWatcher.notesBundleId)
        }
        XCTAssertEqual(reads, 2, "switching to Notes again and again reads once")
        w.disconnect()
    }

    func testAnotherAppComingForwardReadsNothing() async throws {
        var reads = 0
        let clock = Clock()
        let w = watcher(clock: clock) { reads += 1 }
        _ = try await w.syncNow()
        clock.at.addTimeInterval(3600)
        await w.workspaceEvent(bundleId: "com.example.other")
        await w.workspaceEvent(bundleId: nil)
        XCTAssertEqual(reads, 1)
        w.disconnect()
    }

    func testNotesComingForwardNeverReadsBeforeTheFirstReadAfterADisconnectOrWithNotesClosed() async throws {
        var reads = 0
        let clock = Clock()
        defaults.set(true, forKey: AppleNotesWatcher.enabledKey)
        let closed = watcher(clock: clock, open: false) { reads += 1 }
        await closed.workspaceEvent(bundleId: AppleNotesWatcher.notesBundleId)
        XCTAssertEqual(reads, 0, "a notice never launches or reads a Notes that is not open")
        closed.disconnect()
        let off = watcher(clock: clock) { reads += 1 }
        await off.workspaceEvent(bundleId: AppleNotesWatcher.notesBundleId)
        XCTAssertEqual(reads, 0, "disconnected: nothing")
    }

    /// The notice path: a workspace notice for Notes reads once the person's own first read turned it on, none does
    /// after a Disconnect, and a different application's notice reads nothing. (A test process has no bundle id of
    /// its own, so the notice carries one as a string and the watcher is told how to read it.)
    func testTheWorkspaceNoticesAreWiredWhileOnAndRemovedOnDisconnect() async throws {
        var reads = 0
        let clock = Clock()
        let center = NotificationCenter()
        let w = AppleNotesWatcher(defaults: defaults, period: .seconds(3600), now: { clock.at }, center: center,
                                  floor: 0, settle: .zero, bundleOf: { $0.userInfo?["bundle"] as? String },
                                  notesRunning: { true }, read: {
            reads += 1
            return Self.result
        })
        func notice(_ bundle: String, _ name: Notification.Name = NSWorkspace.didActivateApplicationNotification) async throws {
            center.post(name: name, object: nil, userInfo: ["bundle": bundle])
            try await Task.sleep(for: .milliseconds(150))
        }
        _ = try await w.syncNow()
        XCTAssertEqual(reads, 1)
        clock.at.addTimeInterval(1)
        try await notice("com.example.other")
        XCTAssertEqual(reads, 1, "another application's notice reads nothing")
        try await notice(AppleNotesWatcher.notesBundleId)
        XCTAssertEqual(reads, 2, "Notes coming to the front reads")
        clock.at.addTimeInterval(1)
        try await notice(AppleNotesWatcher.notesBundleId, NSWorkspace.didLaunchApplicationNotification)
        XCTAssertEqual(reads, 3, "so does Notes being opened")
        w.disconnect()
        try await notice(AppleNotesWatcher.notesBundleId)
        XCTAssertEqual(reads, 3, "a notice after a disconnect reads nothing")
    }
}
