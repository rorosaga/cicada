import XCTest
@testable import CicadaApp

/// G63 — the sidebar renames and the card's new explanatory lines.
final class ConnectionCopyTests: XCTestCase {

    func testConnectionDecodesHowAndPowers() throws {
        let json = """
        {"id":"claude-plan","label":"Claude plan","kind":"subscription","available":true,
         "connected":true,"billing":"subscription",
         "how":"Signed in to Claude Code on this Mac as `r@example.com`.",
         "powers":["Sleep extraction","Ask","clarification wording"]}
        """
        let c = try JSONDecoder().decode(ConnectionStatus.self, from: Data(json.utf8))
        XCTAssertEqual(c.how, "Signed in to Claude Code on this Mac as `r@example.com`.")
        XCTAssertEqual(c.powersLine, "Sleep extraction · Ask · clarification wording")
    }

    /// An older backend emits neither field; the card must simply not render
    /// those rows rather than failing to decode.
    func testConnectionDecodesWithoutHowAndPowers() throws {
        let json = #"{"id":"ollama-local","label":"Ollama (local)","billing":"free"}"#
        let c = try JSONDecoder().decode(ConnectionStatus.self, from: Data(json.utf8))
        XCTAssertNil(c.how)
        XCTAssertNil(c.powersLine)
    }

    /// R-E26 / the 2026-09-03 ruling: Plans & keys names the plan, never its price.
    func testPlansAndKeysNeverShowsAPrice() {
        let max = ConnectionStatus(id: "claude-plan", label: "Claude plan", kind: "subscription",
                                   available: true, connected: true, plan: "max", planLabel: "Claude Max 20x",
                                   tier: "20x", account: nil, priceUsdMonth: 200, priceNote: "verified 2026-08-28",
                                   billing: "subscription", engineRole: "subscription-cli", detail: nil, login: nil)
        XCTAssertEqual(max.priceLine, "Claude Max 20x")
        XCTAssertFalse(max.priceLine.contains("$"))
    }
}
