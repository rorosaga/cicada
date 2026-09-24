import XCTest
@testable import CicadaApp

@MainActor
final class FakeTabGroupsAPI: TabGroupsSyncAPI {
    var hold = false
    var replies: [Result<TabGroupsSyncResult, any Error>] = []
    private(set) var payloads: [TabGroupsPayload] = []
    func syncTabGroups(_ payload: TabGroupsPayload) async throws -> TabGroupsSyncResult {
        payloads.append(payload)
        if hold { try await Task.sleep(for: .seconds(30)) }
        return replies.isEmpty ? TabGroupsSyncResult(groups: payload.groups.count) : try replies.removeFirst().get()
    }
}

/// Round 4 (G160 first slice; R-SR3, R-SR7, R-SR11) — nothing read before the switch, a changed snapshot posted once,
/// a fold never posted, a stop never a failure. The session file is written by the test.
@MainActor
final class TabGroupWatcherTests: XCTestCase {
    private var dir: URL!
    private var defaults: UserDefaults!
    private var trigger: (@MainActor () -> Void)?

    override func setUp() async throws {
        dir = FileManager.default.temporaryDirectory.appendingPathComponent("TabGroups-\(UUID().uuidString)/Sessions")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defaults = UserDefaults(suiteName: "TabGroups-\(UUID().uuidString)")!
    }

    override func tearDown() async throws { try? FileManager.default.removeItem(at: dir.deletingLastPathComponent()) }

    private func write(title: String = "alpha-project", collapsed: Bool = false, extraTab: Bool = false,
                       version: Int32 = 3) throws {
        var w = SNSSWriter(version: version)
        w.tabWindow(window: 1, tab: 1)
        w.navigation(tab: 1, index: 0, url: "https://example.com/alpha/doc", title: "Design doc")
        if extraTab {
            w.tabWindow(window: 1, tab: 2)
            w.navigation(tab: 2, index: 0, url: "https://example.com/alpha/notes", title: "Notes")
            w.group(tab: 2, high: 1, low: 2)
        }
        w.metadata(high: 1, low: 2, title: title, color: 1, collapsed: collapsed)
        w.group(tab: 1, high: 1, low: 2)
        w.marker()
        try w.data.write(to: dir.appendingPathComponent("Session_1"))
    }

    private func watcher(_ api: FakeTabGroupsAPI, activity: SyncActivity? = nil, lights: BrowserWatcher? = nil,
                         directory: URL? = nil) -> TabGroupWatcher {
        TabGroupWatcher(lights: lights, activity: activity, api: api, defaults: defaults, directory: directory ?? dir,
                        debounce: .milliseconds(20), minimumInterval: .zero,
                        makeWatch: { [weak self] _, onChange in self?.trigger = onChange; return nil },
                        bank: { "alpha" })
    }

    private func eventually(_ what: String, _ condition: () -> Bool) async throws {
        let deadline = ContinuousClock.now + .seconds(3)
        while !condition() {
            guard ContinuousClock.now < deadline else { return XCTFail("timed out waiting for \(what)") }
            try await Task.sleep(for: .milliseconds(20))
        }
    }

    func testNothingIsReadBeforeTheSwitchIsOn() async throws {
        try write()
        let api = FakeTabGroupsAPI()
        let lights = BrowserWatcher(defaults: defaults, channels: [])
        let w = watcher(api, lights: lights)
        w.start()
        try await Task.sleep(for: .milliseconds(80))
        XCTAssertEqual(api.payloads.count, 0)
        XCTAssertEqual(w.status, .off)
        XCTAssertEqual(lights.state(for: TabGroupWatcher.channel), .off)
    }

    func testTurningOnPostsTheSnapshotOnceAndAFoldIsNotAChange() async throws {
        try write()
        let api = FakeTabGroupsAPI()
        let w = watcher(api)
        await w.enable()
        XCTAssertEqual(api.payloads.count, 1)
        let group = try XCTUnwrap(api.payloads.first?.groups.first)
        XCTAssertEqual(group.title, "alpha-project")
        XCTAssertEqual(group.color, "blue")
        XCTAssertEqual(group.tabs.map(\.url), ["https://example.com/alpha/doc"])
        XCTAssertEqual(w.groups.map(\.title), ["alpha-project"])
        XCTAssertEqual(w.status, .watching)
        try write(collapsed: true)
        await w.run(force: false)
        XCTAssertEqual(api.payloads.count, 1, "folding a group never re-posts it (R-SR5)")
        try write(extraTab: true)
        await w.run(force: false)
        XCTAssertEqual(api.payloads.count, 2)
    }

    func testAChangeIsDebouncedIntoOneRun() async throws {
        try write()
        let api = FakeTabGroupsAPI()
        let w = watcher(api)
        await w.enable()
        try write(extraTab: true)
        trigger?(); trigger?(); trigger?()
        try await eventually("the debounced post") { api.payloads.count == 2 }
        try await Task.sleep(for: .milliseconds(100))
        XCTAssertEqual(api.payloads.count, 2)
    }

    func testNoSessionsFolderIsNothingHereNotAFailure() async {
        let api = FakeTabGroupsAPI()
        let lights = BrowserWatcher(defaults: defaults, channels: [])
        let w = watcher(api, lights: lights, directory: dir.appendingPathComponent("missing"))
        await w.enable()
        XCTAssertEqual(w.status, .missing)
        XCTAssertEqual(api.payloads.count, 0)
        XCTAssertEqual(lights.state(for: TabGroupWatcher.channel), .absent)
    }

    func testAnEncryptedFileIsSaidInWordsNeverDecoded() async throws {
        try write(version: 5)
        let w = watcher(FakeTabGroupsAPI())
        await w.enable()
        XCTAssertEqual(w.status, .failed(Copy.tabGroupsUnreadable))
    }

    func testADemoRefusalIsSaidInTheServersWords() async throws {
        try write()
        let api = FakeTabGroupsAPI()
        api.replies = [.failure(APIError.httpError(409, #"{"detail":"Cicada has its demo memory open."}"#))]
        let w = watcher(api)
        await w.enable()
        XCTAssertEqual(w.status, .failed("Cicada has its demo memory open."))
    }

    func testStopEndsTheRunWithoutAFailureAndRecordsNothing() async throws {
        try write()
        let api = FakeTabGroupsAPI()
        api.hold = true
        let activity = SyncActivity()
        let w = watcher(api, activity: activity)
        let running = Task { await w.enable() }
        try await eventually("the run to register") { activity.run(for: TabGroupWatcher.channel)?.cancellable == true }
        activity.cancel(TabGroupWatcher.channel)
        await running.value
        XCTAssertEqual(w.status, .watching)
        XCTAssertNil(activity.run(for: TabGroupWatcher.channel))
        api.hold = false
        await w.run(force: false)
        XCTAssertEqual(api.payloads.count, 2, "no digest was recorded, so the same snapshot is sent again")
    }

    func testTurningOffStopsReadingAndDeletesNothing() async throws {
        try write()
        let api = FakeTabGroupsAPI()
        let w = watcher(api)
        await w.enable()
        w.disable()
        XCTAssertFalse(w.enabled)
        XCTAssertEqual(w.groups, [])
        XCTAssertEqual(w.status, .off)
        XCTAssertEqual(defaults.object(forKey: BrowserWatchPolicy.enabledKey(TabGroupWatcher.channel)) as? Bool, false)
    }
}
