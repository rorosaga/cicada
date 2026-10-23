import XCTest
@testable import CicadaApp

/// R-AG1 — the app's agent list is the backend's (one fixture), and every pill wears a real mark or, for Grok, a
/// neutral glyph until a sourced xAI mark exists (R-AG9).
final class AgentCatalogTests: XCTestCase {
    private struct Fixture: Decodable { let live: [String]; let featured: [String]; let setup: [String] }

    private func fixture() throws -> Fixture {
        let root = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
        return try JSONDecoder().decode(Fixture.self, from: Data(contentsOf:
            root.appendingPathComponent("api/tests/fixtures/agent_catalog.json")))
    }

    func testTheCatalogIsTheBackendsInTheSameOrder() throws {
        let f = try fixture()
        XCTAssertEqual(AgentCatalog.all.map(\.id), f.live)
        XCTAssertEqual(AgentCatalog.featured.map(\.id), f.featured)
        XCTAssertEqual(AgentCatalog.setupHarnesses, Set(f.setup))
    }

    func testEveryMarkShipsAndOnlyGrokAndAnotherAgentUseAGlyph() {
        for entry in AgentCatalog.all {
            if let mark = entry.mark { XCTAssertTrue(LogoImage.exists(name: mark), entry.id) }
        }
        XCTAssertEqual(AgentCatalog.all.filter { $0.mark == nil }.map(\.id), ["grok", "other"])
        // "Another agent" names no vendor: it wears Integrations' own "Other agents" glyph, never another app's mark.
        XCTAssertEqual(AgentCatalog.entry(for: "other")?.symbol, IntegrationHarnessRows.otherAgentsSymbol)
    }

    /// D6: agents left Settings for the Agents page, so Settings search no longer indexes them.
    func testAnotherAgentIsNotFeatured() {
        let other = AgentCatalog.entry(for: "other")!
        XCTAssertFalse(other.featured, "onboarding keeps the owner's nine (R-AG1)")
        XCTAssertEqual(other.kind, .anyAgent)
    }

    func testTheClaudeAppLandsOnTheClaudePill() {
        XCTAssertEqual(AgentCatalog.entry(for: "claude-desktop")?.id, "claude")
        XCTAssertEqual(AgentCatalog.entry(for: "codex")?.id, "codex")
        XCTAssertNil(AgentCatalog.entry(for: "nope"))
    }

    func testAnOlderLivePayloadDecodes() throws {
        let r = try JSONDecoder().decode(AgentLiveResponse.self, from: Data(#"{"agents":[{"id":"codex"}]}"#.utf8))
        XCTAssertEqual(r.agents, [AgentLiveRow(id: "codex")])
        XCTAssertEqual(try JSONDecoder().decode(AgentLiveResponse.self, from: Data("{}".utf8)).agents, [])
    }
}
