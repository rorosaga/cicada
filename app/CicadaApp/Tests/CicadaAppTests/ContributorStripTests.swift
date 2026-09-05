import XCTest
@testable import CicadaApp

/// Track S R-S6 — Contributors as a strip.
///
/// The old section was a wall of expandable rows, each carrying a 4 pt bar
/// whose width was `commitCount / totalCommits` with no label, no tick and no
/// percentage, sitting directly under numbers that were ENTITIES and FILES
/// (critique E2). One page, three scales. The replacement is one chip row over
/// ONE stacked bar whose scale is named — share of entities written — and every
/// decision behind it is a pure function with a table test, so the strip is a
/// renderer and a reviewer reads the rule rather than the layout.
///
/// **Fixtures decode from JSON on purpose.** `Contributor` declares
/// `init(from decoder:)` inside the struct (`Models/Entity.swift`), which
/// suppresses Swift's synthesised memberwise init, so there is nothing else to
/// call — the same reason `StoreTests`/`SourceChannelTests` decode theirs.
private func contributor(_ author: String, kind: String, entities: Int,
                         commits: Int = 1) throws -> Contributor {
    let json = """
    {"author": "\(author)", "kind": "\(kind)", "commitCount": \(commits),
     "entityCount": \(entities), "fileCount": 0, "files": [], "lastActive": ""}
    """
    return try JSONDecoder().decode(Contributor.self, from: Data(json.utf8))
}

final class ContributorStripTests: XCTestCase {

    /// E2 — the old bar's width was `commitCount / totalCommits` with no label,
    /// no tick and no percentage, sitting under numbers that were ENTITIES and
    /// FILES. One bar, one scale, and the scale is named: share of entities
    /// written.
    func testSharesAreOfEntitiesOrderedAndSumToOne() throws {
        let rows = [try contributor("cicada", kind: "system", entities: 10),
                    try contributor("gpt-5.4-mini", kind: "model", entities: 60),
                    try contributor("user", kind: "user", entities: 30)]
        let segments = ContributorShare.segments(rows, limit: 6)
        XCTAssertEqual(segments.map(\.author), ["gpt-5.4-mini", "user", "cicada"],
                       "ordered by ENTITIES desc — never by commits, the bar E2 replaces")
        XCTAssertEqual(segments.map(\.entityCount), [60, 30, 10])
        XCTAssertEqual(segments.reduce(0) { $0 + $1.fraction }, 1.0, accuracy: 0.0001)
        XCTAssertEqual(segments[1].displayName, Copy.you)
    }

    func testAZeroEntityBankYieldsNoSegmentsRatherThanNaN() throws {
        let rows = [try contributor("cicada", kind: "system", entities: 0)]
        XCTAssertTrue(ContributorShare.segments(rows, limit: 6).isEmpty,
                      "0/0 is not 0.0 — an empty track and the empty sentence, never a NaN width")
        XCTAssertTrue(ContributorShare.segments([], limit: 6).isEmpty)
    }

    func testTheTailFoldsIntoOneRemainderChipAboveTheLimit() throws {
        let rows = try (1...9).map { try contributor("model-\($0)", kind: "model", entities: 10) }
        let segments = ContributorShare.segments(rows, limit: 3)
        XCTAssertEqual(segments.count, 3, "the limit INCLUDES the remainder: 2 named + 1 tail")
        XCTAssertEqual(segments.last?.entityCount, 70)
        XCTAssertEqual(segments.reduce(0) { $0 + $1.fraction }, 1.0, accuracy: 0.0001)
    }

    /// E1/E3, R-S13 — the app knows exactly what these three buckets are, so
    /// none of them may render as "?".
    func testEveryBucketHasAName() {
        XCTAssertEqual(ContributorIdentity.displayName(author: "user", kind: "user"), Copy.you)
        XCTAssertEqual(ContributorIdentity.displayName(author: "cicada", kind: "system"),
                       "Cicada · maintenance")
        XCTAssertEqual(ContributorIdentity.displayName(author: "unknown", kind: "unknown"),
                       "Before provenance")
        XCTAssertEqual(ContributorIdentity.displayName(author: "openrouter/z-ai/glm-5.2",
                                                       kind: "model"), "openrouter/z-ai/glm-5.2")
    }

    func testTheSentencePluralisesAndNeverClaimsAModelThatIsNotThere() throws {
        let many = [try contributor("m1", kind: "model", entities: 5, commits: 9),
                    try contributor("m2", kind: "model", entities: 5, commits: 8),
                    try contributor("m3", kind: "model", entities: 5, commits: 3),
                    try contributor("user", kind: "user", entities: 5, commits: 1)]
        XCTAssertEqual(ContributorSummary.sentence(many),
                       "Across 21 commits, 3 models and you wrote this bank.")
        let one = [try contributor("m1", kind: "model", entities: 5, commits: 4)]
        XCTAssertEqual(ContributorSummary.sentence(one),
                       "Across 4 commits, 1 model wrote this bank.")
        let none = [try contributor("cicada", kind: "system", entities: 2, commits: 2)]
        XCTAssertFalse(ContributorSummary.sentence(none).contains("model"),
                       "a maintenance-only bank must not claim a model wrote it")
        XCTAssertEqual(ContributorSummary.sentence([]), "Nothing attributed yet.")
    }
}
