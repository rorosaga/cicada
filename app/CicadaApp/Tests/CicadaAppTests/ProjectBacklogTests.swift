import XCTest
@testable import CicadaApp

/// G150 R-B26 — the demo scenario's backlog wire, generated from a fresh `demo_bank.populate(today=2026-09-23)` by
/// `api/tests/test_backlog_app_fixture.py`, which also fails on any drift (R-PP27's precedent). Synthetic only.
enum BacklogFixtures {
    struct Wire: Decodable {
        let today: String
        let list: BacklogList
        let item: BacklogItem
    }

    static let today = ISODay(year: 2026, month: 9, day: 23)

    /// Resolved from THIS file's own path, never a caller's `#filePath` (`ProjectFixtures`' rule).
    private static let url = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent()   // CicadaAppTests
        .deletingLastPathComponent()   // Tests
        .appendingPathComponent("fixtures/backlog-demo.json")

    static func load(file: StaticString = #filePath, line: UInt = #line) throws -> Wire {
        let wire = try JSONDecoder().decode(Wire.self, from: Data(contentsOf: url))
        XCTAssertEqual(wire.list.items.count, 5, "read \(url.path) — a test over no items passes vacuously",
                       file: file, line: line)
        return wire
    }
}

/// A `BacklogAPI` that answers from a queue and records the ETag each call sent (`FakeProjectsAPI`'s twin).
@MainActor
final class FakeBacklogAPI: BacklogAPI {
    var listReplies: [String: [Result<Conditional<BacklogList>, any Error>]] = [:]
    var itemReplies: [String: [Result<Conditional<BacklogItem>, any Error>]] = [:]
    private(set) var listETags: [String: [String?]] = [:]
    private(set) var itemETags: [String: [String?]] = [:]

    func fetchBacklog(project: String, etag: String?) async throws -> Conditional<BacklogList> {
        listETags[project, default: []].append(etag)
        guard var queue = listReplies[project], !queue.isEmpty else { throw APIError.serverUnreachable }
        let next = queue.removeFirst()
        listReplies[project] = queue
        return try next.get()
    }

    func fetchBacklogItem(project: String, item: String, etag: String?) async throws -> Conditional<BacklogItem> {
        let key = BacklogCache.key(project, item)
        itemETags[key, default: []].append(etag)
        guard var queue = itemReplies[key], !queue.isEmpty else { throw APIError.serverUnreachable }
        let next = queue.removeFirst()
        itemReplies[key] = queue
        return try next.get()
    }
}

/// G150 — the backlog's wire, its pure decisions, its cache and its writes (R-B18, R-B19, R-B22).
@MainActor
final class ProjectBacklogTests: XCTestCase {
    private let us = Locale(identifier: "en_US")

    private func fresh<T>(_ v: T, _ etag: String) -> Result<Conditional<T>, any Error> {
        .success(Conditional(value: v, etag: etag, notModified: false))
    }

    private func notModified<T>(_ etag: String) -> Result<Conditional<T>, any Error> {
        .success(Conditional(value: nil, etag: etag, notModified: true))
    }

    // MARK: The wire

    func testTheDemoWireDecodes() throws {
        let wire = try BacklogFixtures.load()
        XCTAssertEqual(wire.list.prefix, "RAP")
        XCTAssertEqual(wire.list.items.map(\.id), ["RAP5", "RAP3", "RAP4", "RAP2", "RAP1"])
        XCTAssertEqual([BacklogStatus.open, .doing, .done, .dropped].map { wire.list.count($0) }, [2, 1, 1, 1])
        XCTAssertEqual(wire.item.id, "RAP3")
        XCTAssertEqual(wire.item.notes.map(\.byLabel), ["Claude Code", "You"])
        XCTAssertEqual(wire.item.notes.map(\.byKind), ["harness", "user"])
        XCTAssertNil(wire.item.notes[0].authorModel)
        XCTAssertFalse(wire.item.descriptionText.isEmpty)
    }

    func testAPayloadMissingOptionalFieldsStillDecodes() throws {
        let json = #"{"id": "AP1", "project": "alpha-project", "title": "X", "status": "open"}"#
        let item = try JSONDecoder().decode(BacklogItem.self, from: Data(json.utf8))
        XCTAssertEqual(item.summary.noteCount, 0)
        XCTAssertEqual(item.notes, [])
        XCTAssertEqual(item.summary.backlogStatus, .open)
        let odd = try JSONDecoder().decode(BacklogItemSummary.self, from: Data(#"{"id": "AP2", "status": "someday"}"#.utf8))
        XCTAssertEqual(odd.backlogStatus, .open, "an unknown state reads as open, never a crash")
    }

    // MARK: The model (R-B19)

    func testTabsCountEveryStateAndOnlyAllHoldsTheDropped() throws {
        let list = try BacklogFixtures.load().list
        let tabs = BacklogModel.tabs(list)
        XCTAssertEqual(tabs.map(\.label), ["Open", "Doing", "Done", "All"])
        XCTAssertEqual(tabs.map(\.count), [2, 1, 1, 5])
        XCTAssertEqual(BacklogModel.rows(list, tab: .open).map(\.id), ["RAP3", "RAP4"], "the server's order is kept")
        XCTAssertEqual(BacklogModel.rows(list, tab: nil).count, 5)
        XCTAssertFalse(BacklogModel.rows(list, tab: .done).contains { $0.backlogStatus == .dropped })
        XCTAssertEqual(BacklogModel.defaultTab(list), .open)
        XCTAssertEqual(BacklogModel.openCount(list), 3)
    }

    func testTheDefaultTabIsTheFirstThatHoldsAnything() throws {
        var list = try BacklogFixtures.load().list
        list.counts = ["open": 0, "doing": 0, "done": 3, "dropped": 1]
        XCTAssertEqual(BacklogModel.defaultTab(list), .done)
        list.counts = [:]
        XCTAssertEqual(BacklogModel.defaultTab(list), .open)
    }

    func testTheAgeIsTheLastNoteElseTheItemWithTheFullDateAsHelp() throws {
        let rows = Dictionary(uniqueKeysWithValues: try BacklogFixtures.load().list.items.map { ($0.id, $0) })
        let today = BacklogFixtures.today
        let rap3 = try XCTUnwrap(rows["RAP3"])
        XCTAssertEqual(BacklogModel.age(rap3, today: today, locale: us).text, "3d")
        XCTAssertEqual(BacklogModel.age(rap3, today: today, locale: us).help, "Sunday, September 20, 2026")
        XCTAssertEqual(BacklogModel.age(try XCTUnwrap(rows["RAP4"]), today: today, locale: us).text, "6d",
                       "no note: the item's own day")
    }

    func testMovesFollowTheStateAndSayWhatTheyDo() {
        XCTAssertEqual(BacklogModel.moves(from: .open), [.doing, .done, .dropped])
        XCTAssertEqual(BacklogModel.moves(from: .doing), [.done, .dropped])
        XCTAssertEqual(BacklogModel.moves(from: .done), [.open])
        XCTAssertEqual(BacklogModel.moves(from: .dropped), [.open])
        XCTAssertEqual(BacklogStatus.allCases.map(BacklogModel.moveLabel), ["Reopen", "Start", "Mark done", "Drop"])
        XCTAssertEqual(BacklogModel.triageLabel("research"), "Research")
        XCTAssertNil(BacklogModel.triageLabel(nil))
        XCTAssertEqual(BacklogModel.emptyLine(tab: .doing), "Nothing in progress.")
    }

    func testAnAuthorIsNamedInWordsWithTheTurnsModelWhenTheWireKnowsIt() throws {
        let note = try XCTUnwrap(BacklogFixtures.load().item.notes.first)
        XCTAssertEqual(BacklogModel.authorLine(note), "Claude Code")
        var known = note
        known.authorModel = "claude-opus-5-5"
        known.authorEffort = "high"
        XCTAssertEqual(BacklogModel.authorLine(known), "Claude Code · Opus 5.5 · high effort")
        known.authorEffort = "xhigh"
        XCTAssertEqual(BacklogModel.authorLine(known), "Claude Code · Opus 5.5 · extra-high effort")
        XCTAssertEqual(BacklogModel.modelWords("claude-sonnet-5"), "Sonnet 5")
        XCTAssertEqual(BacklogModel.modelWords("gpt-5.5-codex"), "gpt-5.5-codex", "an unknown family reads as its id")
    }

    func testTheItemsHeadingLineSaysWhoAddedItAndWhen() throws {
        let item = try BacklogFixtures.load().item
        XCTAssertEqual(BacklogModel.addedLine(item.summary, today: BacklogFixtures.today, locale: us),
                       "Added by Claude Code · Sep 11")
    }

    // MARK: The cache (R-B18)

    func testTheListIsRevalidatedWithItsETagAndAMoveIsPaintedUntilUnpainted() async throws {
        let api = FakeBacklogAPI()
        api.listReplies["rover-arm-project"] = [fresh(try BacklogFixtures.load().list, "l1"), notModified("l1")]
        let cache = BacklogCache(api: api)
        await cache.refreshList("rover-arm-project")
        await cache.refreshList("rover-arm-project")
        XCTAssertEqual(api.listETags["rover-arm-project"], [nil, "l1"])
        XCTAssertEqual(cache.list("rover-arm-project")?.items.count, 5, "a 304 keeps what was read")
        cache.paint("rover-arm-project", "RAP3", .done)
        let painted = try XCTUnwrap(cache.list("rover-arm-project"))
        XCTAssertEqual(painted.items.first { $0.id == "RAP3" }?.status, "done")
        XCTAssertEqual([painted.count(.open), painted.count(.done)], [1, 2])
        cache.unpaint("rover-arm-project", "RAP3")
        XCTAssertEqual(cache.list("rover-arm-project")?.count(.open), 2)
    }

    func testAMissingProjectIsGoneAndABankSwitchForgetsEverything() async throws {
        let api = FakeBacklogAPI()
        api.listReplies["nope"] = [.failure(APIError.httpError(404, "{}"))]
        api.itemReplies["rover-arm-project/RAP3"] = [fresh(try BacklogFixtures.load().item, "i1")]
        let cache = BacklogCache(api: api)
        await cache.refreshList("nope")
        XCTAssertEqual(cache.listPhase("nope"), .gone)
        await cache.refreshItem("rover-arm-project", "RAP3")
        XCTAssertEqual(cache.item("rover-arm-project", "RAP3")?.summary.title,
                       "Swap the gripper camera for a global-shutter one")
        cache.reset()
        XCTAssertNil(cache.item("rover-arm-project", "RAP3"))
        XCTAssertEqual(cache.listPhase("nope"), .idle)
    }

    func testTheSectionAsksAgainOnlyWhenWhatItsETagsFoldMoves() {
        let a = VersionVector(version: "1", components: ["backlog": "0:0:0", "entities": "1", "episodes": "1",
                                                        "bank": "b"])
        var moved = a.components
        moved["backlog"] = "1:1:9"
        XCTAssertTrue(BacklogRefresh.shouldRevalidate(old: a, new: VersionVector(version: "2", components: moved)))
        var unrelated = a.components
        unrelated["episodes"] = "2"
        XCTAssertFalse(BacklogRefresh.shouldRevalidate(old: a, new: VersionVector(version: "3", components: unrelated)))
    }

    // MARK: Writes (R-B22)

    private func harness() async throws -> (Store, FakeSyncAPI, BacklogCache) {
        let api = FakeSyncAPI()
        let store = Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: api)
        let reads = FakeBacklogAPI()
        reads.listReplies["rover-arm-project"] = [fresh(try BacklogFixtures.load().list, "l1")]
        let cache = BacklogCache(api: reads)
        await cache.refreshList("rover-arm-project")
        return (store, api, cache)
    }

    func testAMoveIsPaintedAtOnceAndSent() async throws {
        let (store, api, cache) = try await harness()
        api.backlogReply = try BacklogFixtures.load().item
        let write = BacklogWrite(projectId: "rover-arm-project",
                                 action: .update(item: "RAP4", change: BacklogChange(status: "done")), cache: cache)
        api.gateWrites = true
        let running = Task { await store.perform(write) }
        await api.waitForParkedWrite()
        XCTAssertEqual(cache.list("rover-arm-project")?.items.first { $0.id == "RAP4" }?.status, "done",
                       "painted before the server answers")
        api.releaseWriteGate()
        let ok = await running.value
        XCTAssertTrue(ok)
        XCTAssertEqual(api.writes.last, "updateBacklogItem:rover-arm-project:RAP4:done:nil")
        XCTAssertEqual(write.result?.id, "RAP3")
    }

    func testA409RollsTheMoveBackAndSaysTheServersSentence() async throws {
        let (store, api, cache) = try await harness()
        api.backlogError = APIError.httpError(409, #"{"detail": "Sleep is writing memory right now, try again in a moment"}"#)
        let write = BacklogWrite(projectId: "rover-arm-project",
                                 action: .note(item: "RAP4", text: "Done.", status: .done), cache: cache)
        let ok = await store.perform(write)
        XCTAssertFalse(ok)
        XCTAssertEqual(cache.list("rover-arm-project")?.items.first { $0.id == "RAP4" }?.status, "open")
        XCTAssertEqual(store.toast, "Sleep is writing memory right now, try again in a moment")
        XCTAssertEqual(api.writes.last, "addBacklogNote:rover-arm-project:RAP4:done")
    }

    func testAnAddPaintsNothingAndA400SaysThePagesOwnWords() async throws {
        let (store, api, cache) = try await harness()
        api.backlogError = APIError.httpError(400, #"{"detail": "links is a list of {kind, ref}; nothing was written"}"#)
        let write = BacklogWrite(projectId: "rover-arm-project", action: .add(title: "New", description: ""),
                                 cache: cache)
        XCTAssertNil(write.paint)
        _ = await store.perform(write)
        XCTAssertEqual(store.toast, Copy.Projects.Backlog.saveFailed)
        XCTAssertEqual(api.writes.last, "addBacklogItem:rover-arm-project:New")
    }
}
