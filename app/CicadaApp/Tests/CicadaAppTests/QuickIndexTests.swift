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
        // The page first; round-4 D2's "Calendar on this Mac" is Integrations' first static row, so it may follow.
        XCTAssertEqual(ids(index.query("integrations"), .settings).first, SettingsSection.integrations.rawValue)
        XCTAssertEqual(index.query("consolidate").rows.first { $0.key.kind == .action }?.title, "Consolidate now")
        XCTAssertEqual(index.query("beta").rows.first { $0.key.kind == .bank }?.destination, .bank(name: "beta-bank"))
        XCTAssertTrue(index.query("switch to default").rows.filter { $0.key.kind == .bank }.isEmpty,
                      "the active bank is not offered")
        var sleeping = FindFixtures.inputs()
        sleeping.isSleeping = true
        sleeping.appearance = .light
        let busy = QuickIndex.build(sleeping)
        XCTAssertEqual(busy.query("stop").rows.first { $0.key.kind == .action }?.destination, .action(.stopConsolidating))
        XCTAssertEqual(busy.query("dark").rows.first { $0.key.kind == .action }?.destination, .action(.darkMode))
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

    /// G136 S6 — an alias finds its node at the alias weight, and a payload
    /// without the field (an older backend, an on-disk cache) still decodes.
    func testAnAliasFindsItsNodeAndAnOldPayloadStillDecodes() throws {
        var inputs = FindFixtures.inputs()
        inputs.nodes.append(FindFixtures.node("bob-example-2", "bob-example-2", aliases: ["beta tester"]))
        XCTAssertEqual(QuickIndex.build(inputs).query("tester").rows.first?.key.id, "bob-example-2")
        let old = try JSONDecoder().decode(GraphNode.self, from: Data(#"{"id": "a", "name": "A", "type": "concept", "confidence": 0.5}"#.utf8))
        XCTAssertEqual(old.aliases, [])
        let new = try JSONDecoder().decode(GraphNode.self, from: Data(#"{"id": "a", "name": "A", "type": "concept", "confidence": 0.5, "aliases": ["alpha"]}"#.utf8))
        XCTAssertEqual(new.aliases, ["alpha"])
    }

    /// R-HS19 — every Settings page and every row is in ⌘K, from Settings' own index, and ⏎ lands on
    /// the row through the one door (R-HS20).
    func testEverySettingIsFoundFromCommandK() {
        let size = index.query("text size").rows.first { $0.group == .settings }
        XCTAssertEqual(size?.key, FindRowKey(kind: .setting, id: SettingsRowID.textSize.rawValue))
        XCTAssertEqual(size?.destination, .settings(.general, row: .textSize))
        XCTAssertEqual(size?.detail, Copy.PaletteSettings.detail(SettingsSection.general.title))
        XCTAssertEqual(index.query("extra usage").rows.first { $0.group == .settings }?.destination,
                       .settings(.engines, row: .engineOverage))
        XCTAssertEqual(index.query("tailscale").rows.first { $0.group == .settings }?.destination,
                       .settings(.remote, row: .page(.remote)))
        XCTAssertEqual(index.query("integrations").rows.first { $0.group == .settings }?.destination,
                       .settings(.integrations, row: nil), "a page lands on the page")
    }

    /// R-HS21 — a page keeps its old key (a recent survives); rows are keyed by row id; none collide.
    func testSettingsKeysAreStableAndUnique() {
        let docs = QuickIndex.settingsDocs()
        XCTAssertEqual(docs.count, SettingsIndex.pageEntries.count + SettingsIndex.staticEntries.count)
        XCTAssertEqual(Set(docs.map(\.row.key)).count, docs.count)
        let sections = Set(SettingsSection.allCases.map(\.rawValue))
        XCTAssertTrue(SettingsIndex.staticIDs.allSatisfy { !sections.contains($0.rawValue) },
                      "a row id equal to a section's raw value would shadow its page")
        XCTAssertTrue(docs.allSatisfy { !$0.row.key.id.contains(":") || $0.row.key.id.hasPrefix("skill:") },
                      "no per-item row (channel:, connection:, agent:) — R-HS19")
    }
}
