import XCTest
@testable import CicadaApp

final class FakeIntakeAPI: IntakeAPI, @unchecked Sendable {
    var sniffs: [String: IntakeSniff] = [:]
    var sniffDelay: [String: Duration] = [:]
    var imports: [String: IntakeImportResponse] = [:]
    var jobPolls: [IntakeJobStatus] = []
    var importedBanks: [String?] = []
    var failImport: Set<String> = []

    func sniffIntake(fileURL: URL, bank: String?) async throws -> IntakeSniff {
        let name = fileURL.lastPathComponent
        if let delay = sniffDelay[name] { try await Task.sleep(for: delay) }
        return sniffs[name] ?? IntakeSniff(reason: "unknown")
    }

    func importIntake(fileURL: URL, bank: String?) async throws -> IntakeImportResponse {
        importedBanks.append(bank)
        if failImport.contains(fileURL.lastPathComponent) { throw APIError.serverUnreachable }
        return imports[fileURL.lastPathComponent] ?? IntakeImportResponse()
    }

    func intakeJob(id: String) async throws -> IntakeJobStatus { jobPolls.removeFirst() }

    func uploadSaved(fileURL: URL) async throws -> UploadResponse {
        UploadResponse(status: "ok", episodesCreated: 2, duplicatesSkipped: 0, message: "", source: "Bookmarks")
    }
}

/// Track I T5 (design §5.1, R-IA20) — one router for every way a file arrives.
@MainActor
final class IntakeRouterTests: XCTestCase {
    private var dir: URL!

    override func setUp() async throws {
        dir = URL(fileURLWithPath: NSTemporaryDirectory()).appendingPathComponent("intake-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
    }

    override func tearDown() async throws { try? FileManager.default.removeItem(at: dir) }

    private func file(_ name: String) throws -> URL {
        let url = dir.appendingPathComponent(name)
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data("{}".utf8).write(to: url)
        return url
    }

    private func chat(_ vendor: String, new: Int = 1) -> IntakeSniff {
        IntakeSniff(recognized: true, kind: "chat", vendor: vendor, origin: "\(vendor)-export", delta: IntakeDelta(new: new))
    }

    private func eventually(_ what: String, _ condition: @MainActor () -> Bool) async throws {
        let deadline = ContinuousClock.now + .seconds(3)
        while ContinuousClock.now < deadline {
            if condition() { return }
            try await Task.sleep(for: .milliseconds(10))
        }
        XCTFail("timed out: \(what)")
    }

    private func isPreview(_ r: IntakeRouter) -> Bool { if case .preview = r.phase { return true }; return false }
    private func isDone(_ r: IntakeRouter) -> Bool { if case .done = r.phase { return true }; return false }

    func testAStaleSniffNeverLandsOnANewerPreview() async throws {
        let api = FakeIntakeAPI()
        api.sniffs = ["old.json": chat("claude"), "new.json": chat("chatgpt")]
        api.sniffDelay["old.json"] = .milliseconds(250)
        let router = IntakeRouter(api: api)
        router.accept(urls: [try file("old.json")], from: .windowDrop)
        router.accept(urls: [try file("new.json")], from: .windowDrop)
        try await eventually("the newer preview") { self.isPreview(router) }
        try await Task.sleep(for: .milliseconds(400))
        guard case .preview(let p) = router.phase else { return XCTFail("\(router.phase)") }
        XCTAssertEqual(p.vendor, "chatgpt", "the older response must be dropped (H1, hoisted)")
        XCTAssertEqual(router.inFlight, 0)
    }

    func testTheFlagIsTrueExactlyWhileARequestRuns() async throws {
        let store = Store()
        let api = FakeIntakeAPI()
        api.sniffs["c.json"] = chat("claude")
        api.sniffDelay["c.json"] = .milliseconds(150)
        let router = IntakeRouter(api: api)
        router.attach(store: store)
        router.accept(urls: [try file("c.json")], from: .windowDrop)
        try await eventually("a sniff in flight") { store.intakeInFlight }
        try await eventually("the preview") { self.isPreview(router) }
        XCTAssertFalse(store.intakeInFlight, "a preview left open is not an intake landing (R-IA20)")
        XCTAssertEqual(router.inFlight, 0)
    }

    func testTheCounterReturnsToZeroOnFailureAndCancel() async throws {
        let api = FakeIntakeAPI()
        api.sniffDelay["slow.json"] = .milliseconds(150)
        let router = IntakeRouter(api: api)
        router.accept(urls: [try file("slow.json")], from: .windowDrop)
        router.cancel()
        XCTAssertEqual(router.phase, .idle)
        try await eventually("the cancelled request to finish") { router.inFlight == 0 }
        XCTAssertEqual(router.phase, .idle, "a cancelled sniff never lands")
        router.accept(urls: [try file("nothing.json")], from: .windowDrop)
        try await eventually("the failure") { if case .failed = router.phase { true } else { false } }
        XCTAssertEqual(router.inFlight, 0)
    }

    func testTheFeedPlusRendersInPlaceAndEverythingElseRaisesTheOverlay() throws {
        let router = IntakeRouter(api: FakeIntakeAPI())
        router.accept(urls: [try file("a.json")], from: .feedPlus(.claude))
        XCTAssertFalse(router.isOverlayPresented)
        XCTAssertEqual(router.host, .feedPlus)
        router.cancel()
        router.accept(urls: [try file("b.json")], from: .dock)
        XCTAssertTrue(router.isOverlayPresented)
        XCTAssertEqual(router.host, .overlay)
    }

    func testConfirmTwiceImportsOnceAndTheCardNeverClosesItself() async throws {
        let api = FakeIntakeAPI()
        api.sniffs["c.json"] = chat("claude", new: 2)
        api.imports["c.json"] = IntakeImportResponse(episodesStaged: 2, vendor: "claude", origin: "claude-export")
        let router = IntakeRouter(api: api)
        router.accept(urls: [try file("c.json")], from: .windowDrop)
        try await eventually("preview") { self.isPreview(router) }
        router.confirm(createBank: { _ in nil })
        router.confirm(createBank: { _ in nil })
        try await eventually("done") { self.isDone(router) }
        XCTAssertEqual(api.importedBanks.count, 1, "a double tap is one import")
        try await Task.sleep(for: .milliseconds(1_700))
        XCTAssertTrue(isDone(router), "the 1.5 s auto-dismiss is gone with UploadOverlay (design §5.2)")
        router.finish()
        XCTAssertEqual(router.phase, .idle)
        XCTAssertFalse(router.isOverlayPresented)
    }

    func testAJobIsFollowedAndItsCountIsOnlyEverWhatItReported() async throws {
        let api = FakeIntakeAPI()
        api.sniffs["big.json"] = chat("claude", new: 50)
        api.imports["big.json"] = IntakeImportResponse(vendor: "claude", job: IntakeJobRef(id: "j1", total: 50))
        api.jobPolls = [IntakeJobStatus(id: "j1", total: 50, staged: 25),
                        IntakeJobStatus(id: "j1", total: 50, staged: 50, created: 50, done: true)]
        let router = IntakeRouter(api: api, sleep: { _ in })
        router.accept(urls: [try file("big.json")], from: .windowDrop)
        try await eventually("preview") { self.isPreview(router) }
        router.confirm(createBank: { _ in nil })
        try await eventually("done") { self.isDone(router) }
        guard case .done(let outcome) = router.phase else { return XCTFail() }
        XCTAssertEqual(outcome.created, 50)
        XCTAssertEqual(router.inFlight, 0)
    }

    func testANewMemoryIsCreatedBeforeTheImportAndTargeted() async throws {
        let api = FakeIntakeAPI()
        api.sniffs["c.json"] = chat("claude")
        let router = IntakeRouter(api: api)
        router.accept(urls: [try file("c.json")], from: .windowDrop)
        try await eventually("preview") { self.isPreview(router) }
        router.retarget(.newBank("alpha-project"))
        router.confirm(createBank: { name in name == "alpha-project" ? "alpha-project" : nil })
        try await eventually("done") { self.isDone(router) }
        XCTAssertEqual(api.importedBanks, ["alpha-project"])
    }

    /// Final review, finding 3: "New memory" chosen, then Cancel, then a new
    /// drop — the target must be the active bank again, and the import must go
    /// where the (router-derived) picker says.
    func testACancelledNewMemoryNeverOutlivesItsPreview() async throws {
        let api = FakeIntakeAPI()
        api.sniffs["c.json"] = chat("claude")
        api.sniffs["d.json"] = chat("claude")
        let router = IntakeRouter(api: api)
        router.accept(urls: [try file("c.json")], from: .windowDrop)
        try await eventually("preview") { self.isPreview(router) }
        router.retarget(.newBank("alpha-project"))
        XCTAssertEqual(router.target, .newBank("alpha-project"))
        router.cancel()
        XCTAssertEqual(router.target, .active)
        router.accept(urls: [try file("d.json")], from: .windowDrop)
        try await eventually("second preview") { self.isPreview(router) }
        XCTAssertEqual(router.target, .active)
        router.confirm(createBank: { _ in XCTFail("no memory was asked for"); return nil })
        try await eventually("done") { self.isDone(router) }
        XCTAssertEqual(api.importedBanks, [nil])
    }

    func testADropWhileImportingIsRefused() async throws {
        let api = FakeIntakeAPI()
        api.sniffs["c.json"] = chat("claude")
        api.imports["c.json"] = IntakeImportResponse(job: IntakeJobRef(id: "j", total: 1))
        api.jobPolls = [IntakeJobStatus(id: "j", total: 1, staged: 1, created: 1, done: true)]
        let gate = AsyncStream<Void>.makeStream()
        let router = IntakeRouter(api: api, sleep: { _ in for await _ in gate.stream { break } })
        router.accept(urls: [try file("c.json")], from: .windowDrop)
        try await eventually("preview") { self.isPreview(router) }
        router.confirm(createBank: { _ in nil })
        try await eventually("importing") { if case .importing = router.phase { true } else { false } }
        router.accept(urls: [try file("d.json")], from: .windowDrop)
        if case .importing = router.phase {} else { XCTFail("a second drop replaced an import in flight") }
        gate.continuation.yield()
        try await eventually("done") { self.isDone(router) }
    }

    func testCommitImportsWithoutAPreview() async throws {
        let api = FakeIntakeAPI()
        api.imports["c.json"] = IntakeImportResponse(episodesStaged: 3, vendor: "claude")
        let router = IntakeRouter(api: api)
        let outcome = await router.commit(urls: [try file("c.json")], from: .welcome)
        XCTAssertEqual(outcome.created, 3)
        XCTAssertEqual(router.inFlight, 0)
        XCTAssertEqual(router.phase, .idle, "the Welcome's Start path never opens the panel")
    }

    func testExpandWalksFoldersSkipsNoiseAndCaps() throws {
        _ = try file("export/conversations.json")
        _ = try file("export/user.json")
        _ = try file("export/images/a.png")
        _ = try file("export/.DS_Store")
        _ = try file("export/__MACOSX/conversations.json")
        let (files, capped) = IntakeRouter.expand([dir.appendingPathComponent("export")])
        XCTAssertEqual(files.map(\.lastPathComponent), ["conversations.json", "user.json"],
                       "user.json is kept: skipping it is the backend's job, reported by name")
        XCTAssertFalse(capped)
        for i in 0..<(IntakeRouter.maxFiles + 5) { _ = try file("many/f\(i).json") }
        let (many, cappedMany) = IntakeRouter.expand([dir.appendingPathComponent("many")])
        XCTAssertEqual(many.count, IntakeRouter.maxFiles)
        XCTAssertTrue(cappedMany)
    }

    /// R-IB15 — while the Welcome shows, every arrival is staged on it; nothing imports before Start.
    func testWhileTheWelcomeShowsEveryArrivalIsStagedAndNothingImports() async throws {
        let api = FakeIntakeAPI()
        api.sniffs = ["conversations.json": chat("chatgpt", new: 4)]
        let router = IntakeRouter(api: api)
        router.welcomeActive = true
        router.accept(urls: [try file("conversations.json")], from: .dock)
        try await eventually("a staged row") { router.welcomeDrops.count == 1 }
        XCTAssertFalse(router.isOverlayPresented, "the Welcome is the host; no overlay hidden under it")
        XCTAssertEqual(router.phase, .idle)
        XCTAssertTrue(api.importedBanks.isEmpty, "nothing imports before Start (principle 2)")
        XCTAssertEqual(router.welcomeDrops.first?.preview.delta.new, 4)
        XCTAssertEqual(router.inFlight, 0)
    }

    func testPresentWhileTheWelcomeShowsAsksItToChooseAFile() {
        let router = IntakeRouter(api: FakeIntakeAPI())
        router.welcomeActive = true
        router.present(from: .fileMenu)
        XCTAssertEqual(router.welcomeChooseRequest, 1)
        XCTAssertFalse(router.isOverlayPresented)
    }

    func testAStagedDropCommitsChatAndSavedFilesThroughTheirOwnRoutes() async throws {
        let api = FakeIntakeAPI()
        api.sniffs = ["conversations.json": chat("claude"),
                      "bookmarks.html": IntakeSniff(recognized: true, kind: "saved", counts: IntakeCounts(items: 2))]
        api.imports = ["conversations.json": IntakeImportResponse(episodesStaged: 1)]
        let router = IntakeRouter(api: api)
        router.welcomeActive = true
        router.accept(urls: [try file("conversations.json"), try file("bookmarks.html")], from: .welcome)
        try await eventually("staged") { router.welcomeDrops.count == 1 }
        let outcome = await router.commitWelcomeDrop(router.welcomeDrops[0].id)
        XCTAssertEqual(outcome?.created, 1)
        XCTAssertEqual(outcome?.savedCreated, 2, "saved content commits through /sources/upload (R-IA32)")
        XCTAssertTrue(router.welcomeDrops.isEmpty)
    }

    /// R-IB15 — a commit that failed keeps its drop staged, so Getting started's Retry has
    /// something to commit (a forgotten drop would fail "The import didn't finish." forever).
    func testAFailedStagedCommitStaysForRetry() async throws {
        let api = FakeIntakeAPI()
        api.sniffs = ["conversations.json": chat("claude")]
        api.failImport = ["conversations.json"]
        let router = IntakeRouter(api: api)
        router.welcomeActive = true
        router.accept(urls: [try file("conversations.json")], from: .welcome)
        try await eventually("staged") { router.welcomeDrops.count == 1 }
        let outcome = await router.commitWelcomeDrop(router.welcomeDrops[0].id)
        XCTAssertEqual(outcome?.failures.count, 1)
        XCTAssertEqual(router.welcomeDrops.count, 1)
    }

    /// R-IB15 — a Dock open that reached the overlay before the gate raised the Welcome is
    /// moved onto the Welcome, never left as a preview hidden underneath it.
    func testRaisingTheWelcomeAdoptsASniffAlreadyOnTheOverlay() async throws {
        let api = FakeIntakeAPI()
        api.sniffs = ["conversations.json": chat("chatgpt", new: 3)]
        let router = IntakeRouter(api: api)
        router.accept(urls: [try file("conversations.json")], from: .dock)
        XCTAssertTrue(router.isOverlayPresented)
        router.welcomeActive = true
        XCTAssertFalse(router.isOverlayPresented, "nothing hidden under the Welcome")
        try await eventually("adopted") { router.welcomeDrops.count == 1 }
        XCTAssertEqual(router.phase, .idle)
        XCTAssertTrue(api.importedBanks.isEmpty, "adopting is staging, never importing")
    }

    /// R-IB22 — a sniff of the export someone was waiting for clears that wait.
    func testASniffedExportReportsItsVendor() async throws {
        let api = FakeIntakeAPI()
        api.sniffs = ["conversations.json": chat("chatgpt")]
        let router = IntakeRouter(api: api)
        var sniffed: [String] = []
        router.onVendorSniffed = { sniffed.append($0) }
        router.accept(urls: [try file("conversations.json")], from: .windowDrop)
        try await eventually("the preview") { self.isPreview(router) }
        XCTAssertEqual(sniffed, ["chatgpt"])
    }

    /// R-IB22 — the export arriving on the Welcome clears its wait too: the
    /// Welcome's staging is a sniff like any other.
    func testAnExportStagedOnTheWelcomeReportsItsVendor() async throws {
        let api = FakeIntakeAPI()
        api.sniffs = ["conversations.json": chat("claude")]
        let router = IntakeRouter(api: api)
        var sniffed: [String] = []
        router.onVendorSniffed = { sniffed.append($0) }
        router.welcomeActive = true
        router.accept(urls: [try file("conversations.json")], from: .welcome)
        try await eventually("staged") { router.welcomeDrops.count == 1 }
        XCTAssertEqual(sniffed, ["claude"])
    }
}
