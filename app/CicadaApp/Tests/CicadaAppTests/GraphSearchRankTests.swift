import XCTest
@testable import CicadaApp

/// G123: the typeahead ranks prefix > word-start > substring, then degree, then name.
final class GraphSearchRankTests: XCTestCase {
    private let items: [(id: String, name: String, degree: Int)] = [
        ("a", "Alpha Project", 3),
        ("b", "Beta alpha notes", 9),
        ("c", "Gamma", 1),
        ("d", "Alphabet Inc", 7),
        ("e", "Catalpha", 20),
    ]

    func testPrefixBeatsWordStartBeatsSubstring() {
        let ids = GraphViewModel.rankNames(items, query: "alpha")
        XCTAssertEqual(ids, ["d", "a", "b", "e"])   // prefix by degree (d 7 > a 3), then word-start, then substring
    }

    func testEmptyQueryReturnsNothingAndLimitHolds() {
        XCTAssertEqual(GraphViewModel.rankNames(items, query: "   "), [])
        XCTAssertEqual(GraphViewModel.rankNames(items, query: "a", limit: 2).count, 2)
    }

    func testCaseInsensitive() {
        XCTAssertEqual(GraphViewModel.rankNames(items, query: "GAM"), ["c"])
    }
}
