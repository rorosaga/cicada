import XCTest
@testable import CicadaApp

/// The owner's decisions after the app hunt and headless QA (2026-10-16): bookmarks catch up on a bank switch like the
/// other readers (per-memory seen-state, never the demo); the outbox never lets another memory's refused post block the
/// active memory's; Settings → Sleep's "Scheduled runs may use my plan" and a schedule's no-engine warning (ruling 4b,
/// decision 2). Synthetic files and placeholder memories only.
@MainActor
final class BookmarksPerBankTests: XCTestCase {
    private var dir: URL!
    private var defaults: UserDefaults!
    private var store: Store!
    private let suite = "cicada.bookmarks-per-bank.tests"

    override func setUp() async throws {
        dir = URL(fileURLWithPath: NSTemporaryDirectory()).appendingPathComponent("cicada-bpb-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defaults = UserDefaults(suiteName: suite)
        defaults.removePersistentDomain(forName: suite)
        store = Store()
        try "{\"roots\": {}}".write(to: dir.appendingPathComponent("Bookmarks"), atomically: true, encoding: .utf8)
        defaults.set(true, forKey: BrowserWatchPolicy.enabledKey("chrome-bookmarks"))
    }

    override func tearDown() async throws {
        defaults.removePersistentDomain(forName: suite)
        try? FileManager.default.removeItem(at: dir)
    }

    private func watcher(bank: @escaping @MainActor () -> String, demo: @escaping @MainActor () -> Bool = { false },
                         onSync: @escaping @MainActor (String?) -> Void) -> BrowserWatcher {
        BrowserWatcher(
            defaults: defaults,
            channels: [("chrome-bookmarks", .chromeBookmarks)],
            paths: { [dir] _ in [dir!.appendingPathComponent("Bookmarks")] },
            debounce: .milliseconds(60), minimumInterval: .milliseconds(1),
            performSync: { _, _ in onSync(BankScope.origin); return "ok" },
            bank: bank, isDemo: demo)
    }

    private func settle(_ condition: @MainActor () -> Bool) async throws {
        let deadline = ContinuousClock.now + .seconds(5)
        while ContinuousClock.now < deadline, !condition() { try await Task.sleep(for: .milliseconds(25)) }
        try await Task.sleep(for: .milliseconds(100))
    }

    func testANewlyActiveMemoryCatchesUpOnTheBookmarksAndPostsToItself() async throws {
        var bank = "alpha"
        var posted: [String?] = []
        let w = watcher(bank: { bank }, onSync: { posted.append($0) })
        w.start(store: store)
        defer { w.stop() }
        try await settle { !posted.isEmpty }
        XCTAssertEqual(posted, ["alpha"], "the first memory reads the browser once")
        await w.catchUp()
        XCTAssertEqual(posted, ["alpha"], "an unchanged file is not read again for the same memory")
        bank = "beta"
        await w.bankChanged()
        XCTAssertEqual(posted, ["alpha", "beta"], "the memory switched to gets its own read, bound to it")
        bank = "alpha"
        await w.bankChanged()
        XCTAssertEqual(posted, ["alpha", "beta"], "each memory keeps its own seen-state")
        XCTAssertNotNil(defaults.data(forKey: BrowserWatcher.signatureKey("chrome-bookmarks", bank: "alpha")))
        XCTAssertNotNil(defaults.data(forKey: BrowserWatcher.signatureKey("chrome-bookmarks", bank: "beta")))
    }

    func testTheDemoIsNeverCaughtUp() async throws {
        var posted: [String?] = []
        let w = watcher(bank: { "demo" }, demo: { true }, onSync: { posted.append($0) })
        w.start(store: store)
        defer { w.stop() }
        try await Task.sleep(for: .milliseconds(200))
        await w.bankChanged()
        await w.catchUp()
        XCTAssertTrue(posted.isEmpty)
    }

    func testTheOldSignatureMovesToTheMemoryThatReadsItFirstAndConsentStays() async throws {
        defaults.removeObject(forKey: BrowserWatchPolicy.enabledKey("chrome-bookmarks"))   // a pre-consent install
        let sig = BrowserFileSignature(path: dir.appendingPathComponent("Bookmarks").path)!
        defaults.set(try JSONEncoder().encode(sig), forKey: BrowserWatcher.legacySignatureKey("chrome-bookmarks"))
        var bank = "alpha"
        var posted: [String?] = []
        let w = watcher(bank: { bank }, onSync: { posted.append($0) })
        XCTAssertTrue(w.isEnabled("chrome-bookmarks"), "a stored signature still counts as consent")
        w.start(store: store)
        defer { w.stop() }
        try await Task.sleep(for: .milliseconds(200))
        await w.catchUp()
        XCTAssertTrue(posted.isEmpty, "the memory that had it is not re-read after the upgrade")
        XCTAssertNil(defaults.data(forKey: BrowserWatcher.legacySignatureKey("chrome-bookmarks")))
        XCTAssertEqual(defaults.object(forKey: BrowserWatchPolicy.enabledKey("chrome-bookmarks")) as? Bool, true)
        bank = "beta"
        XCTAssertTrue(w.isEnabled("chrome-bookmarks"), "another memory never reads as turned off")
        await w.bankChanged()
        XCTAssertEqual(posted, ["beta"])
    }

    /// Review blocker: the app's Store names its placeholder "default" until `hydrate()` reads the roster, and the
    /// watcher starts before that. The old signature must not move to "default" then — it would leave the memory that
    /// really had it to read every bookmark again — only to the memory the roster says is active.
    func testTheOldSignatureWaitsForTheActiveMemoryBeforeMoving() async throws {
        let sig = BrowserFileSignature(path: dir.appendingPathComponent("Bookmarks").path)!
        defaults.set(try JSONEncoder().encode(sig), forKey: BrowserWatcher.legacySignatureKey("chrome-bookmarks"))
        var posted: [String?] = []
        let w = BrowserWatcher(
            defaults: defaults,
            channels: [("chrome-bookmarks", .chromeBookmarks)],
            paths: { [dir] _ in [dir!.appendingPathComponent("Bookmarks")] },
            debounce: .milliseconds(60), minimumInterval: .milliseconds(1),
            performSync: { _, _ in posted.append(BankScope.origin); return "ok" })
        w.start(store: store)          // Store.bank is still "default"; no roster yet
        defer { w.stop() }
        try await Task.sleep(for: .milliseconds(200))
        await w.catchUp()
        XCTAssertTrue(posted.isEmpty, "the unchanged file is not read again before the memory is known")
        XCTAssertNotNil(defaults.data(forKey: BrowserWatcher.legacySignatureKey("chrome-bookmarks")))
        XCTAssertNil(defaults.data(forKey: BrowserWatcher.signatureKey("chrome-bookmarks", bank: "default")))
        let alpha = MemoryBank(name: "alpha", active: true, entityCount: 0, episodeCount: 0, createdAt: "2026-10-01",
                               description: nil)
        store.banks.value = BanksResponse(banks: [alpha], active: "alpha")
        store.bank = "alpha"
        await w.bankChanged()
        XCTAssertTrue(posted.isEmpty, "the memory that had the bookmarks is not re-read after the upgrade")
        XCTAssertNotNil(defaults.data(forKey: BrowserWatcher.signatureKey("chrome-bookmarks", bank: "alpha")))
        XCTAssertNil(defaults.data(forKey: BrowserWatcher.legacySignatureKey("chrome-bookmarks")))
    }
}

private actor SentLog {
    var items: [String] = []
    func add(_ item: String) { items.append(item) }
}

final class OutboxLanesTests: XCTestCase {
    private var home: URL!

    override func setUpWithError() throws {
        home = FileManager.default.temporaryDirectory.appendingPathComponent("outbox-lanes-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: home, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws { try? FileManager.default.removeItem(at: home) }

    private func put(_ outbox: ReaderOutbox, _ body: String, bank: String, path: String = "/sources/sync-notes",
                     at seconds: TimeInterval) async throws {
        let stamped = ReaderOutbox(folder: ReaderOutbox.folder(cicadaHome: home),
                                   now: { Date(timeIntervalSince1970: 1_800_000_000 + seconds) })
        try await stamped.put(method: "POST", path: path, body: Data(body.utf8), bank: bank)
    }

    func testAnotherMemorysRefusedPostNeverBlocksTheActiveMemorys() async throws {
        let outbox = ReaderOutbox(folder: ReaderOutbox.folder(cicadaHome: home))
        try await put(outbox, "alpha-1", bank: "alpha", at: 1)
        try await put(outbox, "alpha-2", bank: "alpha", at: 2)
        try await put(outbox, "beta-1", bank: "beta", at: 3)
        let sent = SentLog()
        let result = await outbox.flush { entry in
            await sent.add(String(decoding: entry.body, as: UTF8.self))
            return entry.bank == "alpha" ? 409 : 200     // alpha is not the active memory any more
        }
        let order = await sent.items
        XCTAssertEqual(order, ["alpha-1", "beta-1"], "alpha-2 waits behind alpha-1; beta goes")
        XCTAssertEqual(result, ReaderOutbox.FlushResult(sent: 1, dropped: 0, waiting: 2))
        let left = await outbox.entries().map { String(decoding: $0.entry.body, as: UTF8.self) }
        XCTAssertEqual(left, ["alpha-1", "alpha-2"], "skipped, kept, in order")
    }

    /// G202 (D2): a flush for one server sends only the posts read for it; the same memory name on another server is
    /// another lane, and its posts wait for their own server.
    func testAFlushForOneServerNeverSendsAnotherServersPosts() async throws {
        let outbox = ReaderOutbox(folder: ReaderOutbox.folder(cicadaHome: home))
        try await outbox.put(method: "POST", path: "/sources/sync-notes", body: Data("a".utf8), bank: "default",
                             bankId: "id-a", base: "https://a.example.ts.net")
        try await outbox.put(method: "POST", path: "/sources/sync-notes", body: Data("b".utf8), bank: "default",
                             bankId: "id-b", base: "https://b.example.ts.net")
        try await outbox.put(method: "POST", path: "/sources/sync-notes", body: Data("legacy".utf8), bank: "default")
        let sent = SentLog()
        let result = await outbox.flush(for: "https://b.example.ts.net/") { entry in
            await sent.add(String(decoding: entry.body, as: UTF8.self))
            return 200
        }
        let order = await sent.items
        XCTAssertEqual(Set(order), ["b", "legacy"], "a post with no server goes where the app points, as before")
        XCTAssertEqual(result, ReaderOutbox.FlushResult(sent: 2, dropped: 0, waiting: 0))
        let left = await outbox.waiting(for: "https://b.example.ts.net")
        XCTAssertTrue(left == (0, 1))
        XCTAssertNotEqual(ReaderOutbox.lane(ReaderOutbox.Entry(method: "POST", path: "/p", body: Data(), bank: "default",
                                                               queuedAt: Date(), base: "https://a.example.ts.net")),
                          ReaderOutbox.lane(ReaderOutbox.Entry(method: "POST", path: "/p", body: Data(), bank: "default",
                                                               queuedAt: Date(), base: "https://b.example.ts.net")))
    }

    func testNoAnswerOrARefusedTokenStillStopsEverything() async throws {
        let outbox = ReaderOutbox(folder: ReaderOutbox.folder(cicadaHome: home))
        try await put(outbox, "alpha-1", bank: "alpha", at: 1)
        try await put(outbox, "beta-1", bank: "beta", at: 2)
        for answer in [nil, 401, 403] as [Int?] {
            let sent = SentLog()
            _ = await outbox.flush { entry in await sent.add(String(decoding: entry.body, as: UTF8.self)); return answer }
            let count = await sent.items.count
            XCTAssertEqual(count, 1, "\(String(describing: answer)) is about the server or this device: stop")
        }
    }
}

final class ScheduledPlanCopyTests: XCTestCase {
    func testTheSwitchAndItsCostDecodeAndAreSent() throws {
        let options = try JSONDecoder().decode(SleepRunOptions.self, from: Data(#"{"batchSize":25,"scheduledUsePlan":true}"#.utf8))
        XCTAssertTrue(options.scheduledUsePlan)
        let older = try JSONDecoder().decode(SleepRunOptions.self, from: Data(#"{"batchSize":25}"#.utf8))
        XCTAssertFalse(older.scheduledUsePlan, "an older server reads as off")
        XCTAssertEqual(SleepRunOptionsChange.scheduledUsePlan(true).body["scheduledUsePlan"] as? Bool, true)
        XCTAssertTrue(Copy.ServerPlan.usePlanOnDetail.contains("limits"), "what it costs is said where it is turned on")
    }

    func testAScheduleWarningDecodesIsNeverSentBackAndOffersThePlanFirst() throws {
        let body = #"{"mode":"daily","hour":4,"minute":0,"warning":"Scheduled runs have no engine they may use here.","warningCode":"no_engine"}"#
        let config = try JSONDecoder().decode(ScheduleConfig.self, from: Data(body.utf8))
        XCTAssertEqual(config.warningCode, "no_engine")
        let sent = String(decoding: try JSONEncoder().encode(config), as: UTF8.self)
        XCTAssertFalse(sent.contains("warning"), "the warning is the server's to say, never written back")
        let line = try XCTUnwrap(Copy.ServerPlan.warningLine(config.warning, code: config.warningCode))
        XCTAssertLessThan(try XCTUnwrap(line.range(of: "Connect your plan")).lowerBound,
                          try XCTUnwrap(line.range(of: "API key")).lowerBound)
        XCTAssertNil(Copy.ServerPlan.warningLine(nil, code: nil))
    }

    func testTheCopyNamesNoProvider() {
        let strings = [Copy.ServerPlan.usePlanTitle, Copy.ServerPlan.usePlanOnDetail, Copy.ServerPlan.usePlanOffDetail]
            + ["no_engine", "plan_signed_out", "plan_not_chosen", "local_down"].compactMap(Copy.ServerPlan.fix(for:))
        for text in strings {
            for name in ["Claude", "Anthropic", "ChatGPT", "OpenAI", "Ollama", "Codex"] {
                XCTAssertFalse(text.contains(name), "\(name) in \(text)")
            }
        }
    }

    func testTheSwitchHasASettingsRowThatSearchFinds() {
        XCTAssertTrue(SettingsIndex.staticIDs.contains(.sleepUsePlan))
    }
}
