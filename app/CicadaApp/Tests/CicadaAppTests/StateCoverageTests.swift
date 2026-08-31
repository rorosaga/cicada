import XCTest
@testable import CicadaApp

/// G68 §2.10 — every list has a stable row identity, and every page can tell
/// "never loaded" from "loaded and empty".
@MainActor
final class StateCoverageTests: XCTestCase {

    private func tempCache() -> SnapshotCache {
        SnapshotCache(root: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString))
    }

    // MARK: Ask row identity

    /// `AskCitation.id` is the ENTITY id, so two snippets from one entity
    /// collide inside a `ForEach` and only one chip renders. Gaps are bare
    /// strings and collide on repetition the same way.
    func testDuplicateCitationsAndGapsStillGetDistinctRowIds() {
        let citation = AskCitation(entityId: "capstone", entityName: "Capstone",
                                   filePath: "entities/capstone.md", snippet: "…")
        let answer = AskResponse(answer: "…", confidence: 0.5,
                                 citations: [citation, citation],
                                 gaps: ["when it is due", "when it is due"])

        XCTAssertEqual(Set(answer.citations.map(\.id)).count, 1, "precondition: the model ids collide")
        XCTAssertEqual(Set(answer.gaps).count, 1, "precondition: the gap strings collide")

        XCTAssertEqual(answer.citationRows.count, 2)
        XCTAssertEqual(Set(answer.citationRows.map(\.id)).count, 2)
        XCTAssertEqual(answer.gapRows.count, 2)
        XCTAssertEqual(Set(answer.gapRows.map(\.id)).count, 2)
        XCTAssertEqual(answer.gapRows.map(\.text), ["when it is due", "when it is due"])
    }

    // MARK: Heatmap weekday column

    /// Seven rows, three of them deliberately blank. `id: \.self` collapsed
    /// the blanks into one and slid Wed/Fri off their grid rows.
    func testWeekdayColumnHasSevenRowsThatNeedIndexIdentity() {
        XCTAssertEqual(HeatmapView.weekdayLabels.count, 7)
        XCTAssertLessThan(Set(HeatmapView.weekdayLabels).count, 7,
                          "if the labels were all distinct, id: \\.self would be fine")
    }

    // MARK: Contributors — never-loaded vs empty

    func testContributorsReportsNeverLoadedUntilAPayloadLands() async throws {
        let api = FakeSyncAPI()
        let store = Store(cache: tempCache(), api: api)
        let vm = ContributorsViewModel(store: store)

        XCTAssertFalse(vm.hasLoaded)
        XCTAssertNil(vm.errorMessage)

        api.replies[.contributors] = .failure
        await store.refresh([.contributors])
        XCTAssertFalse(vm.hasLoaded)
        XCTAssertEqual(vm.errorMessage, "Couldn't load contributors")

        api.replies[.contributors] = .value([Contributor]())
        await vm.load()
        XCTAssertTrue(vm.hasLoaded)
        XCTAssertNil(vm.errorMessage, "loaded-and-empty is not an error")
        XCTAssertTrue(vm.contributors.isEmpty)
    }

    /// A failed background refresh over good data stays silent — same rule the
    /// Store uses for `toast`.
    func testAFailedRefreshOverGoodDataDoesNotSurfaceAnError() async throws {
        let api = FakeSyncAPI()
        let store = Store(cache: tempCache(), api: api)
        let vm = ContributorsViewModel(store: store)

        api.replies[.contributors] = .value([Contributor]())
        await store.refresh([.contributors])
        api.replies[.contributors] = .failure
        await store.refresh([.contributors])

        XCTAssertTrue(vm.hasLoaded)
        XCTAssertNil(vm.errorMessage)
    }

    // MARK: Inbox — no "All caught up" mid-load

    func testInboxIsLoadingWhileTheFirstFetchIsStillInFlight() async throws {
        let api = FakeSyncAPI()
        let store = Store(cache: tempCache(), api: api)
        let vm = InboxViewModel(store: store)

        api.gatedDomains = [.inbox]
        api.replies[.inbox] = .value([InboxItem]())
        let refresh = Task { await store.refresh([.inbox]) }
        try await Task.sleep(for: .milliseconds(100))

        XCTAssertTrue(vm.isLoading, "must not fall through to the empty state mid-load")
        XCTAssertTrue(vm.items.isEmpty)

        api.releaseGate(.inbox)
        await refresh.value
        XCTAssertFalse(vm.isLoading)
        XCTAssertTrue(vm.items.isEmpty, "now it really is empty")
    }
}
