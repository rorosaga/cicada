import XCTest
@testable import CicadaApp

/// R-E27 — every connection that names a mark ships it, and the names come
/// from the one map that owns vendor marks.
final class ConnectionMarkTests: XCTestCase {
    func testEveryConnectionMarkShipsInTheBundle() throws {
        for id in ["claude-plan", "chatgpt-plan", "ollama-local", "byok-openai", "byok-anthropic", "byok-gemini"] {
            let name = try XCTUnwrap(ConnectionMark.logoName(connectionId: id), id)
            XCTAssertTrue(LogoImage.exists(name: name), "\(id) → \(name)")
        }
    }

    func testOpenRouterKeepsTheKeyGlyph() {
        XCTAssertNil(ConnectionMark.logoName(connectionId: "byok-openrouter"))
        XCTAssertEqual(ConnectionMark.symbol(isKeyBased: true), "key.fill")
    }

    /// Spec R-E4: the plan cards wear Claude's and ChatGPT's marks — the plan
    /// the person pays for, not the CLI Cicada drives.
    func testThePlansWearTheirVendorsMarks() {
        XCTAssertEqual(ConnectionMark.logoName(connectionId: "claude-plan"), ContributorIdentity.logoName(provider: "anthropic"))
        XCTAssertEqual(ConnectionMark.logoName(connectionId: "chatgpt-plan"), ContributorIdentity.logoName(provider: "openai"))
        XCTAssertEqual(ConnectionMark.logoName(connectionId: "claude-plan"), "claude")
        XCTAssertEqual(ConnectionMark.logoName(connectionId: "chatgpt-plan"), "chatgpt")
    }
}
