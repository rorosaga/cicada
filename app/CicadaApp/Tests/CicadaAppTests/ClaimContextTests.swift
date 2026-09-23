import XCTest
@testable import CicadaApp

/// F1 (R-FX1, R-FX3) — the app's half of `api/services/claim_contexts.py`,
/// held to the same table (`api/tests/fixtures/claim_contexts.json`). The
/// owner's Graph legend listed a raw folder id as a context, and a click on a
/// satellite opened an empty card.
final class ClaimContextTests: XCTestCase {
    private struct Case: Decodable {
        let context: String
        let valid: Bool
        let display: String?
    }
    private struct Fixture: Decodable { let cases: [Case] }

    private func fixture() throws -> [Case] {
        // …/Tests/CicadaAppTests/<this file> → …/CicadaApp → …/app → repo root
        let root = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()   // CicadaAppTests
            .deletingLastPathComponent()   // Tests
            .deletingLastPathComponent()   // CicadaApp (package root)
            .deletingLastPathComponent()   // app
            .deletingLastPathComponent()   // repo root
        let file = root.appendingPathComponent("api/tests/fixtures/claim_contexts.json")
        let cases = try JSONDecoder().decode(Fixture.self, from: Data(contentsOf: file)).cases
        XCTAssertGreaterThanOrEqual(cases.count, 12, "a table test over 0 rows passes vacuously")
        return cases
    }

    func testTheSharedTable() throws {
        for c in try fixture() {
            XCTAssertEqual(ClaimContext.isValid(c.context), c.valid, c.context)
            if let display = c.display {
                XCTAssertEqual(ClaimContext.displayName(c.context), display, c.context)
            }
        }
    }

    func testTheLegendListsOnlyRealContexts() {
        let nodes = [
            GraphNode(id: "media-arxiv-2401-00001", name: "Paper Alpha", type: .media,
                      contexts: ["general", "folder:f0a1b2:reading-list"]),
            GraphNode(id: "bob-example#engineering", name: "Engineering", type: .person,
                      isFacet: true, parentId: "bob-example", context: "engineering"),
        ]
        let links = [GraphEdge(source: "media-arxiv-2401-00001", target: "alpha-project",
                               label: "cited-in", context: "as of 2026-05-01")]
        XCTAssertEqual(ClaimContext.roster(nodes: nodes, links: links), ["engineering", "general"])
    }

    func testASatelliteClickOpensItsSubjectsCard() {
        let nodes = [
            GraphNode(id: "bob-example", name: "Bob Example", type: .person),
            GraphNode(id: "bob-example#family", name: "Family", type: .person,
                      isFacet: true, parentId: "bob-example", context: "family"),
        ]
        XCTAssertEqual(ClaimContext.cardTarget(for: "bob-example#family", in: nodes), "bob-example")
        XCTAssertEqual(ClaimContext.cardTarget(for: "bob-example", in: nodes), "bob-example")
        XCTAssertEqual(ClaimContext.cardTarget(for: "not-loaded#x", in: nodes), "not-loaded#x")
    }
}
