import XCTest
@testable import CicadaApp

/// G136 S3 / plan R-SU5, R-SU13 — the instant tier indexes what the app
/// already holds, and nothing twice.
final class QuickIndexTests: XCTestCase {
    private let index = QuickIndex.build(FindFixtures.inputs())

    private func ids(_ result: QuickIndex.Result, _ group: FindGroupID) -> [String] {
        result.rows.filter { $0.group == group }.map(\.key.id)
    }

    func testEntitiesSkipFacetsHubsAndMediaNodesAndASavedItemIsListedOnce() {
        let result = index.query("alpha")
        XCTAssertEqual(ids(result, .entities), ["alpha-project"])
        XCTAssertEqual(result.rows.filter { $0.key.kind == .media }.map(\.key.id), ["media-alpha"])
        XCTAssertEqual(result.counts[.entities], 1)
        let row = result.rows.first { $0.key.id == "alpha-project" }
        XCTAssertEqual(row?.titleRanges, [[0, 5]], "the title's own bold run")
        XCTAssertEqual(row?.destination, .entity(id: "alpha-project"))
        XCTAssertEqual(row?.secondary, .entityInClusters(id: "alpha-project"))
    }

    func testTagsSummariesInboxCausesAndSourceCardsAreFound() {
        XCTAssertEqual(ids(index.query("robotics"), .entities), ["alpha-project"])
        XCTAssertEqual(ids(index.query("retrieval"), .entities), ["alpha-project"])
        XCTAssertEqual(ids(index.query("paused"), .inbox), ["inbox-001"])
        XCTAssertEqual(ids(index.query("claude"), .sources), ["harness:claude-code"])
        XCTAssertEqual(index.query("claude").rows.first { $0.key.kind == .source }?.mark, .origin("claude-code"))
    }

    func testSettingsActionsAndBanksReflectTheirState() {
        XCTAssertEqual(ids(index.query("integrations"), .settings), [SettingsSection.integrations.rawValue])
        XCTAssertEqual(index.query("consolidate").rows.first?.title, "Consolidate now")
        XCTAssertEqual(index.query("beta").rows.first { $0.key.kind == .bank }?.destination, .bank(name: "beta-bank"))
        XCTAssertTrue(index.query("switch to default").rows.filter { $0.key.kind == .bank }.isEmpty,
                      "the active bank is not offered")
        var sleeping = FindFixtures.inputs()
        sleeping.isSleeping = true
        sleeping.appearance = .light
        let busy = QuickIndex.build(sleeping)
        XCTAssertEqual(busy.query("stop").rows.first?.destination, .action(.stopConsolidating))
        XCTAssertEqual(busy.query("dark").rows.first?.destination, .action(.darkMode))
        var rested = FindFixtures.inputs()
        rested.unprocessed = 0
        XCTAssertTrue(QuickIndex.build(rested).query("consolidate").rows.filter { $0.key.kind == .action }.isEmpty,
                      "nothing queued, nothing to run — the Sleep page's own gate")
    }

    func testTheEmptyStateResolvesRecentsAndSuggestsOnlyWhatIsTrue() {
        let recents = [FindRowKey(kind: .entity, id: "bob-example"), FindRowKey(kind: .entity, id: "gone")]
        let empty = index.emptyState(recents: recents)
        XCTAssertEqual(empty.groups[.recent]?.map(\.key.id), ["bob-example"], "an id that no longer resolves is dropped")
        XCTAssertEqual(empty.groups[.suggested]?.map(\.title), ["Consolidate now", "Answer 1 question"])
        var quiet = FindFixtures.inputs()
        quiet.unprocessed = 0
        quiet.inbox = []
        XCTAssertNil(QuickIndex.build(quiet).emptyState(recents: []).groups[.suggested])
    }

    func testAskHistoryIsFoundAndTheNewestThreeAreOffered() {
        var inputs = FindFixtures.inputs()
        inputs.askHistory = (0..<5).map { AskHistoryEntry(question: "question \($0)", askedAt: Date(timeIntervalSince1970: Double(100 - $0)), answer: nil) }
        let built = QuickIndex.build(inputs)
        XCTAssertEqual(built.emptyState(recents: []).groups[.askedBefore]?.map(\.title), ["question 0", "question 1", "question 2"])
        XCTAssertEqual(built.query("question 4").rows.first { $0.group == .askedBefore }?.destination,
                       .askedBefore(question: "question 4"))
    }

    func testFeedSearchReadsDescriptionUrlAndOriginAndKeepsOrder() {
        let a = FindFixtures.media("m-a", title: "First", url: "https://example.com/alpha-notes", description: "about retrieval")
        let b = FindFixtures.media("m-b", title: "Second", origin: "chrome-bookmark")
        XCTAssertEqual(FeedSearch.filter([a, b], query: "retrieval").map(\.mediaEntityId), ["m-a"])
        XCTAssertEqual(FeedSearch.filter([a, b], query: "notes").map(\.mediaEntityId), ["m-a"], "a URL word")
        XCTAssertEqual(FeedSearch.filter([a, b], query: "chrome").map(\.mediaEntityId), ["m-b"])
        XCTAssertEqual(FeedSearch.filter([b, a], query: "").map(\.mediaEntityId), ["m-b", "m-a"], "R-SU20: order kept")
    }

    func testInboxSearchReadsQuestionEntityAndCause() {
        let items = [FindFixtures.inbox("i1", question: "Still tracking alpha-project?", entityName: "alpha-project"),
                     FindFixtures.inbox("i2", question: "Which role?", entityName: "bob-example", excerpt: "bob-example moved teams")]
        XCTAssertEqual(InboxSearch.filter(items, query: "teams").map(\.id), ["i2"])
        XCTAssertEqual(InboxSearch.filter(items, query: "alpha").map(\.id), ["i1"])
        XCTAssertEqual(InboxSearch.filter(items, query: "").map(\.id), ["i1", "i2"])
    }
}
