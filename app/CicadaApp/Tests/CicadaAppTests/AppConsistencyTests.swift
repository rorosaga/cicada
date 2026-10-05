import SwiftUI
import XCTest
@testable import CicadaApp

/// Audit 2026-10-02 batch 3 — late entity reads (A03) and the source editor's write order and draft (A05/A06).
@MainActor
final class StaleEntityReadTests: XCTestCase {

    private func body(_ text: String) throws -> Entity {
        try JSONDecoder().decode(Entity.self, from: Data("""
        {"id":"x","name":"X","type":"project","status":"active","confidence":0.9,
         "created":"2026-01-01","lastReferenced":"2026-01-02","decayRate":0.05,
         "markdownContent":"\(text)"}
        """.utf8))
    }

    private func makeStore(_ api: FakeSyncAPI) -> Store {
        Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)),
              api: api)
    }

    func testAReadAnsweredAfterABankSwitchIsDiscarded() async throws {
        let api = FakeSyncAPI()
        api.entities["x"] = try body("# From bank A")
        let store = makeStore(api)
        api.gateEntityFetch = true
        let read = Task { await store.entity("x") }
        await api.waitForParkedEntityFetch()
        api.entities["x"] = try body("# From bank B")
        _ = await store.perform(ActivateBank(name: "B"))
        api.releaseEntityGate()
        let late = await read.value
        XCTAssertNil(late, "bank A's body is never handed to a bank B caller")
        XCTAssertNil(store.entities["x"], "nor cached under bank B")
        let fresh = await store.entity("x")
        XCTAssertEqual(fresh?.markdownContent, "# From bank B")
    }

    func testAReadStartedBeforeAnInvalidationRefetches() async throws {
        let api = FakeSyncAPI()
        api.entities["x"] = try body("# Before the edit")
        let store = makeStore(api)
        api.gateEntityFetch = true
        let read = Task { await store.entity("x") }
        await api.waitForParkedEntityFetch()
        api.entities["x"] = try body("# After the edit")
        store.invalidateEntity("x")
        api.releaseEntityGate()
        let result = await read.value
        XCTAssertEqual(result?.markdownContent, "# After the edit", "the pre-mutation answer is not returned")
        XCTAssertEqual(store.entities["x"]?.markdownContent, "# After the edit", "nor cached")
        XCTAssertEqual(api.entityFetches, 2)
    }

    func testAReadStartedBeforeAFullInvalidationRefetches() async throws {
        let api = FakeSyncAPI()
        api.entities["x"] = try body("# Old graph")
        let store = makeStore(api)
        api.gateEntityFetch = true
        let read = Task { await store.entity("x") }
        await api.waitForParkedEntityFetch()
        api.entities["x"] = try body("# New graph")
        store.invalidateAllEntities()
        api.releaseEntityGate()
        let result = await read.value
        XCTAssertEqual(result?.markdownContent, "# New graph")
        XCTAssertEqual(store.entities["x"]?.markdownContent, "# New graph")
    }

    func testAnUndisturbedReadIsCachedOnce() async throws {
        let api = FakeSyncAPI()
        api.entities["x"] = try body("# Body")
        let store = makeStore(api)
        _ = await store.entity("x")
        _ = await store.entity("x")
        XCTAssertEqual(api.entityFetches, 1)
    }
}

@MainActor
final class SourceWriteOrderTests: XCTestCase {
    private final class Box { var sources: [EntitySource] = [] }

    private func setup() throws -> (Store, FakeSyncAPI, Box, Binding<[EntitySource]>) {
        let api = FakeSyncAPI()
        let store = Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: api)
        let box = Box()
        box.sources = try SourcesFixtures.load()
        return (store, api, box, Binding(get: { box.sources }, set: { box.sources = $0 }))
    }

    func testASecondWriteWaitsForTheFirstAndAFailureRollsBackOnlyItsOwnChange() async throws {
        let (store, api, box, binding) = try setup()
        let first = try XCTUnwrap(box.sources.first)
        let second = try XCTUnwrap(box.sources.last)
        XCTAssertNotEqual(first.id, second.id)
        let afterSecond = box.sources.filter { $0.id != second.id }
        api.sourceReplies = [.failure(APIError.serverUnreachable), .success(afterSecond)]
        api.gateWrites = true
        let queue = SourceWriteQueue()
        let a = queue.run { await store.perform(EntitySourceWrite(entityId: "bob-example", source: first,
                                                                  change: .remove, sources: binding)) }
        let b = queue.run { await store.perform(EntitySourceWrite(entityId: "bob-example", source: second,
                                                                  change: .remove, sources: binding)) }
        await api.waitForParkedWrite()
        for _ in 0..<1_000 { await Task.yield() }   // give an unserialised B every chance to send
        XCTAssertEqual(api.writes.count, 1, "B's request is not sent while A is in flight")
        api.gateWrites = false
        api.releaseWriteGate()
        let landedA = await a.value
        let landedB = await b.value
        XCTAssertFalse(landedA)
        XCTAssertTrue(landedB)
        XCTAssertEqual(box.sources, afterSecond, "A's rollback did not undo B, and B's answer is the list")
        XCTAssertTrue(box.sources.contains { $0.id == first.id }, "A's removal was rolled back")
    }

    func testTwoSuccessesLandInSubmissionOrder() async throws {
        let (store, api, box, binding) = try setup()
        let first = try XCTUnwrap(box.sources.first)
        let second = try XCTUnwrap(box.sources.last)
        let afterFirst = box.sources.filter { $0.id != first.id }
        let afterBoth = afterFirst.filter { $0.id != second.id }
        api.sourceReplies = [.success(afterFirst), .success(afterBoth)]
        let queue = SourceWriteQueue()
        let a = queue.run { await store.perform(EntitySourceWrite(entityId: "bob-example", source: first,
                                                                  change: .remove, sources: binding)) }
        let b = queue.run { await store.perform(EntitySourceWrite(entityId: "bob-example", source: second,
                                                                  change: .remove, sources: binding)) }
        _ = await a.value
        _ = await b.value
        XCTAssertEqual(box.sources, afterBoth)
    }

    func testAWriteAnsweredAfterTheCardMovedToAnotherEntityLeavesThatEntitysList() async throws {
        let (store, api, box, binding) = try setup()
        let first = try XCTUnwrap(box.sources.first)
        var onEntity = "bob-example"
        api.sourceReplies = [.success([]), .failure(APIError.serverUnreachable)]
        api.gateWrites = true
        let write = EntitySourceWrite(entityId: "bob-example", source: first, change: .remove, sources: binding,
                                      isCurrent: { onEntity == "bob-example" })
        let task = Task { await store.perform(write) }
        await api.waitForParkedWrite()
        // The person moves the card to another page; the card refetches that page's list.
        onEntity = "alpha-project"
        let otherList = Array(box.sources.suffix(2))
        box.sources = otherList
        api.gateWrites = false
        api.releaseWriteGate()
        _ = await task.value
        XCTAssertEqual(box.sources, otherList, "bob-example's answer never lands on alpha-project's card")

        // A failure's rollback must not restore bob-example's list onto it either.
        onEntity = "bob-example"
        box.sources = try SourcesFixtures.load()
        let second = try XCTUnwrap(box.sources.last)
        api.gateWrites = true
        let failing = EntitySourceWrite(entityId: "bob-example", source: second, change: .remove, sources: binding,
                                        isCurrent: { onEntity == "bob-example" })
        let task2 = Task { await store.perform(failing) }
        await api.waitForParkedWrite()
        onEntity = "alpha-project"
        box.sources = otherList
        api.gateWrites = false
        api.releaseWriteGate()
        let landed = await task2.value
        XCTAssertFalse(landed)
        XCTAssertEqual(box.sources, otherList)
    }

    func testAFailedAddToastsTheServersSentenceAndLeavesTheList() async throws {
        let (store, api, box, binding) = try setup()
        let before = box.sources
        api.sourceError = APIError.httpError(409, #"{"detail":"Sleep is writing — try again in a moment"}"#)
        let landed = await store.perform(EntitySourceAdd(entityId: "bob-example", ref: "https://example.com",
                                                         predicate: nil, sources: binding))
        XCTAssertFalse(landed)
        XCTAssertEqual(box.sources, before)
        XCTAssertEqual(store.toast, "Sleep is writing — try again in a moment")
    }

    func testAnAddReplacesTheListWithTheServersAnswer() async throws {
        let (store, api, box, binding) = try setup()
        let answer = Array(box.sources.prefix(1))
        api.sourceReply = answer
        let landed = await store.perform(EntitySourceAdd(entityId: "bob-example", ref: "https://example.com",
                                                         predicate: "website", sources: binding))
        XCTAssertTrue(landed)
        XCTAssertEqual(box.sources, answer)
        XCTAssertEqual(api.writes.last, "addEntitySource:bob-example:https://example.com:website")
    }
}

final class SourceDraftTests: XCTestCase {
    func testWhatTheFieldHoldsAfterAnAdd() {
        XCTAssertEqual(SourceDraft.afterAdd(submitted: "a.example", current: "a.example", landed: true), "")
        XCTAssertEqual(SourceDraft.afterAdd(submitted: "a.example", current: "b.example", landed: true), "b.example")
        XCTAssertEqual(SourceDraft.afterAdd(submitted: "a.example", current: "a.example", landed: false), "a.example")
        XCTAssertEqual(SourceDraft.afterAdd(submitted: "a.example", current: "", landed: false), "a.example")
        XCTAssertEqual(SourceDraft.afterAdd(submitted: "a.example", current: "b.example", landed: false), "b.example")
    }
}
