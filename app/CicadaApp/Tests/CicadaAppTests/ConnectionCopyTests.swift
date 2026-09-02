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

    /// The tier picker is a cost-estimate control only, and only Claude Max
    /// has tiers — a Claude Pro or an Ollama card must not show it.
    func testTierPickerOnlyForClaudeMax() {
        func make(_ id: String, _ plan: String?) -> ConnectionStatus {
            ConnectionStatus(id: id, label: id, kind: "subscription", available: true,
                             connected: true, plan: plan, planLabel: nil, tier: nil,
                             account: nil, priceUsdMonth: nil, priceNote: nil,
                             billing: "subscription", engineRole: nil, detail: nil,
                             how: nil, powers: [], login: nil)
        }
        XCTAssertTrue(make("claude-plan", "max").showsTierPicker)
        XCTAssertFalse(make("claude-plan", "pro").showsTierPicker)
        XCTAssertFalse(make("chatgpt-plan", "pro").showsTierPicker)
        XCTAssertFalse(make("ollama-local", nil).showsTierPicker)
    }
}
